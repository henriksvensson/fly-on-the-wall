import httpx
import pytest

from fly_on_the_wall.providers.openai_cleanup import OpenAICleanupError, cleanup_transcript


def test_cleanup_transcript_calls_openai_and_returns_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        body = request.read().decode()
        assert "Person B" in body
        assert "Example Company" in body
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Person B: Hej där."}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    cleaned = cleanup_transcript(
        "Person B: hej där",
        glossary_terms=["Example Company"],
        api_key="test-key",
        client=client,
    )

    assert cleaned == "Person B: Hej där."


def test_cleanup_transcript_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(OpenAICleanupError, match="Missing OPENAI_API_KEY"):
        cleanup_transcript("Person B: hej")
