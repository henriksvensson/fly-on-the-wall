from unittest.mock import Mock

import httpx
import pytest

from fly_on_the_wall.providers.openai_cleanup import (
    DEFAULT_CLEANUP_TIMEOUT_SECONDS,
    OpenAICleanupError,
    cleanup_transcript,
)


def test_cleanup_transcript_calls_openai_and_returns_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        body = request.read().decode()
        assert "Person A" in body
        assert "Example Company" in body
        assert "manuscript-style dialogue" in body
        assert "filler/discourse-marker words" in body
        assert "liksom" in body
        assert "clear literal/comparative" in body
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Person A: Hej där."}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    cleaned = cleanup_transcript(
        "Person A: hej där",
        glossary_terms=["Example Company"],
        api_key="test-key",
        client=client,
    )

    assert cleaned == "Person A: Hej där."


def test_cleanup_transcript_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("keyring.get_password", lambda service, provider: None)

    with pytest.raises(OpenAICleanupError, match="Missing OPENAI_API_KEY"):
        cleanup_transcript("Person A: hej")


def test_cleanup_transcript_uses_long_default_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Mock()
    client.post.return_value = httpx.Response(
        200,
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        json={"choices": [{"message": {"content": "Person A: Hej."}}]},
    )
    client.close.return_value = None
    client_class = Mock(return_value=client)
    monkeypatch.setattr("fly_on_the_wall.providers.openai_cleanup.httpx.Client", client_class)

    cleaned = cleanup_transcript("Person A: hej", api_key="test-key")

    assert cleaned == "Person A: Hej."
    client_class.assert_called_once_with(timeout=DEFAULT_CLEANUP_TIMEOUT_SECONDS)
