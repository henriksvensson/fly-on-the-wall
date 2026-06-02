from __future__ import annotations

import httpx

from fly_on_the_wall.providers.openai_cleanup import API_URL
from fly_on_the_wall.secrets import get_api_key

DEFAULT_ANALYSIS_MODEL = "gpt-5.4-mini"


class OpenAIAnalysisError(RuntimeError):
    """Raised when OpenAI meeting analysis fails."""


def analyze_meeting(
    transcript_markdown: str,
    meeting_context: str | None = None,
    model: str = DEFAULT_ANALYSIS_MODEL,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> str:
    resolved_api_key = api_key or get_api_key("openai")
    if not resolved_api_key:
        raise OpenAIAnalysisError("Missing OPENAI_API_KEY.")

    close_client = client is None
    http_client = client or httpx.Client(timeout=180)
    try:
        response = http_client.post(
            API_URL,
            headers={"Authorization": f"Bearer {resolved_api_key}"},
            json={
                "model": model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": _system_prompt(meeting_context)},
                    {"role": "user", "content": transcript_markdown},
                ],
            },
        )
        response.raise_for_status()
        return _extract_content(response.json())
    except httpx.HTTPStatusError as exc:
        message = f"OpenAI HTTP {exc.response.status_code}: {exc.response.text}"
        raise OpenAIAnalysisError(message) from exc
    except httpx.HTTPError as exc:
        raise OpenAIAnalysisError(f"OpenAI request failed: {exc}") from exc
    finally:
        if close_client:
            http_client.close()


def fallback_analysis(error: str | None = None) -> str:
    detail = f" Analysis failed: {error}" if error else ""
    return f"""
# Meeting Analysis

## Summary

None identified.{detail}

## Decisions

None identified.

## Action Items

None identified.

## Open Questions

None identified.

## Important Details

None identified.
""".strip()


def _system_prompt(meeting_context: str | None) -> str:
    context = meeting_context or "none"
    return f"""
You analyze meeting transcripts for a personal note-taker.
Return concise Markdown with exactly these headings:
# Meeting Analysis
## Summary
## Decisions
## Action Items
## Open Questions
## Important Details

Keep it short and prioritized. Do not invent facts.
If a section has no useful content, write "None identified."
For action items, use: - Owner: task. Due: date or Not mentioned.
Meeting context: {context}
""".strip()


def _extract_content(response: dict) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenAIAnalysisError("OpenAI response did not contain message content.") from exc
    return str(content).strip()
