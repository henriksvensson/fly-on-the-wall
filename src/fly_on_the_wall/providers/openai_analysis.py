from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from fly_on_the_wall.providers.openai_cleanup import API_URL
from fly_on_the_wall.secrets import get_api_key

DEFAULT_ANALYSIS_MODEL = "gpt-5.4-mini"


class OpenAIAnalysisError(RuntimeError):
    """Raised when OpenAI meeting analysis fails."""


@dataclass(frozen=True)
class OpenAIRequestOptions:
    model: str = DEFAULT_ANALYSIS_MODEL
    api_key: str | None = None
    client: httpx.Client | None = None
    usage_callback: Callable[[dict], None] | None = None


@dataclass(frozen=True)
class AnalysisRequest:
    transcript_markdown: str
    meeting_context: str | None = None
    options: OpenAIRequestOptions = field(default_factory=OpenAIRequestOptions)


@dataclass(frozen=True)
class TitleRequest:
    transcript_markdown: str
    analysis_markdown: str
    meeting_context: str | None = None
    options: OpenAIRequestOptions = field(default_factory=OpenAIRequestOptions)


@dataclass(frozen=True)
class ChatCompletionRequest:
    system_prompt: str
    user_prompt: str
    options: OpenAIRequestOptions
    timeout_seconds: int


def analyze_meeting(request: AnalysisRequest) -> str:
    return _post_chat_completion(
        ChatCompletionRequest(
            system_prompt=_system_prompt(request.meeting_context),
            user_prompt=request.transcript_markdown,
            options=request.options,
            timeout_seconds=180,
        )
    )


def suggest_meeting_title(request: TitleRequest) -> str:
    content = _post_chat_completion(
        ChatCompletionRequest(
            system_prompt=_title_system_prompt(request.meeting_context),
            user_prompt=(
                f"Transcript:\n{request.transcript_markdown}\n\n"
                f"Analysis:\n{request.analysis_markdown}"
            ),
            options=request.options,
            timeout_seconds=60,
        )
    )
    return _clean_title(content)


def _post_chat_completion(request: ChatCompletionRequest) -> str:
    resolved_api_key = _require_api_key(request.options)
    close_client = request.options.client is None
    http_client = request.options.client or httpx.Client(timeout=request.timeout_seconds)
    try:
        response_json = _send_chat_completion(http_client, resolved_api_key, request)
        _record_usage(request.options, response_json)
        return _extract_content(response_json)
    except httpx.HTTPStatusError as exc:
        message = f"OpenAI HTTP {exc.response.status_code}: {exc.response.text}"
        raise OpenAIAnalysisError(message) from exc
    except httpx.HTTPError as exc:
        raise OpenAIAnalysisError(f"OpenAI request failed: {exc}") from exc
    finally:
        _close_client(http_client, close_client)


def _require_api_key(options: OpenAIRequestOptions) -> str:
    resolved_api_key = options.api_key or get_api_key("openai")
    if not resolved_api_key:
        raise OpenAIAnalysisError("Missing OPENAI_API_KEY.")
    return resolved_api_key


def _close_client(client: httpx.Client, close_client: bool) -> None:
    if close_client:
        client.close()


def _send_chat_completion(
    client: httpx.Client, api_key: str, request: ChatCompletionRequest
) -> dict:
    response = client.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": request.options.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
        },
    )
    response.raise_for_status()
    return response.json()


def _record_usage(options: OpenAIRequestOptions, response_json: dict) -> None:
    if options.usage_callback is not None:
        options.usage_callback(response_json)


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


def _title_system_prompt(meeting_context: str | None) -> str:
    context = meeting_context or "none"
    return f"""
You name meeting transcripts for a personal note-taker.
Return only one title, with no Markdown, labels, quotes, or punctuation wrapper.
Use 3 to 8 words.
Prefer concrete names, projects, organizations, and topics from the transcript.
Do not include dates unless the date is central to the meeting topic.
Do not return generic titles like "Meeting Summary" or "Team Meeting".
If the transcript has no meaningful content, return an empty string.
Meeting context: {context}
""".strip()


def _extract_content(response: dict) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenAIAnalysisError("OpenAI response did not contain message content.") from exc
    return str(content).strip()


def _clean_title(value: str) -> str:
    title = value.strip().strip('"\'`')
    if title.lower() in {"meeting summary", "team meeting", "meeting", "untitled"}:
        return ""
    return " ".join(title.split())
