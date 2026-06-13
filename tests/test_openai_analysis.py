import httpx

from fly_on_the_wall.providers.openai_analysis import (
    AnalysisRequest,
    OpenAIRequestOptions,
    TitleRequest,
    analyze_meeting,
    suggest_meeting_title,
)


def test_analyze_meeting_sends_glossary_terms() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert "Hejare: Company name" in body
        assert "Person A" in body
        assert "Do not insert glossary terms" in body
        return httpx.Response(200, json={"choices": [{"message": {"content": "# Meeting Analysis"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = analyze_meeting(
        AnalysisRequest(
            "**Person A:** Hej",
            glossary_terms=["Hejare: Company name", "Person A"],
            options=OpenAIRequestOptions(api_key="test-key", client=client),
        )
    )

    assert result == "# Meeting Analysis"


def test_suggest_meeting_title_sends_glossary_terms() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert "Hejare: Company name" in body
        assert "Person A" in body
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hejare Planning"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = suggest_meeting_title(
        TitleRequest(
            "**Person A:** Hej",
            "# Meeting Analysis",
            glossary_terms=["Hejare: Company name", "Person A"],
            options=OpenAIRequestOptions(api_key="test-key", client=client),
        )
    )

    assert result == "Hejare Planning"
