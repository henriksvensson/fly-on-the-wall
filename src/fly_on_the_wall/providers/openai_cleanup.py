from __future__ import annotations

import httpx

from fly_on_the_wall.config import get_api_key

API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"


class OpenAICleanupError(RuntimeError):
    """Raised when OpenAI cleanup fails."""


def cleanup_transcript(
    transcript: str,
    glossary_terms: list[str] | None = None,
    meeting_context: str | None = None,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> str:
    resolved_api_key = api_key or get_api_key("openai")
    if not resolved_api_key:
        raise OpenAICleanupError("Missing OPENAI_API_KEY.")

    close_client = client is None
    http_client = client or httpx.Client(timeout=120)
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
        return _extract_content(response.json())
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
You lightly clean meeting transcripts.
Preserve speaker names, speaker order, source labels, language, and meaning.
Fix punctuation, casing, obvious spacing, and lightly broken phrasing.
Do not summarize, invent details, remove uncertainty markers, or add new content.
Return only the cleaned transcript.
Meeting context: {context}
Glossary terms: {glossary}
""".strip()


def _extract_content(response: dict) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenAICleanupError("OpenAI response did not contain message content.") from exc
    return str(content).strip()
