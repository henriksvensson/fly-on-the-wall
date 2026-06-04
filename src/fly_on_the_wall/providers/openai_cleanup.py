from __future__ import annotations

from collections.abc import Callable

import httpx

from fly_on_the_wall.secrets import get_api_key

API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_CLEANUP_TIMEOUT_SECONDS = 1800
CLEANUP_PROMPT_VERSION = "2026-06-04-manuscript-cleanup-v4"


class OpenAICleanupError(RuntimeError):
    """Raised when OpenAI cleanup fails."""


def cleanup_transcript(
    transcript: str,
    glossary_terms: list[str] | None = None,
    meeting_context: str | None = None,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    client: httpx.Client | None = None,
    usage_callback: Callable[[dict], None] | None = None,
) -> str:
    resolved_api_key = api_key or get_api_key("openai")
    if not resolved_api_key:
        raise OpenAICleanupError("Missing OPENAI_API_KEY.")

    close_client = client is None
    http_client = client or httpx.Client(timeout=DEFAULT_CLEANUP_TIMEOUT_SECONDS)
    try:
        response = http_client.post(
            API_URL,
            headers={"Authorization": f"Bearer {resolved_api_key}"},
            json={
                "model": model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": _system_prompt(glossary_terms, meeting_context)},
                    {"role": "user", "content": transcript},
                ],
            },
        )
        response.raise_for_status()
        response_json = response.json()
        if usage_callback is not None:
            usage_callback(response_json)
        return _extract_content(response_json)
    except httpx.HTTPStatusError as exc:
        message = f"OpenAI HTTP {exc.response.status_code}: {exc.response.text}"
        raise OpenAICleanupError(message) from exc
    except httpx.HTTPError as exc:
        raise OpenAICleanupError(f"OpenAI request failed: {exc}") from exc
    finally:
        if close_client:
            http_client.close()


def _system_prompt(glossary_terms: list[str] | None, meeting_context: str | None) -> str:
    glossary = ", ".join(glossary_terms or []) or "none"
    context = meeting_context or "none"
    return f"""
You clean meeting transcripts into readable manuscript-style dialogue.
Preserve speaker names, speaker order, source labels, language, and meaning.
Make the transcript pleasant to read rather than word-for-word: fix punctuation, casing,
obvious spacing, and lightly broken phrasing.
Remove verbal tics, hesitation sounds, repeated false starts, repeated words, and
filler/discourse-marker words when they only function as speaking habits rather than meaning.
For Swedish transcripts, words such as "liksom", "alltså", "såhär", "du vet", "eh" and
"äh" are usually conversational fillers. Default to removing them when the sentence still
means the same thing without them. Keep them only when they are inside quoted wording, part
of an idiom, or used with clear literal/comparative meaning, such as "på samma sätt som" or
"som om". Do not keep them for vague emphasis, hesitation, self-correction, or rhythm.
Prefer complete readable sentences over literal STT fragments, but do not summarize,
invent details, remove uncertainty markers, or add new content.
Preserve standalone acknowledgements such as yes/no/okay/mm and Swedish ja/nej/okej/mm.
Return only the cleaned manuscript.
Meeting context: {context}
Glossary terms: {glossary}
""".strip()


def _extract_content(response: dict) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenAICleanupError("OpenAI response did not contain message content.") from exc
    return str(content).strip()
