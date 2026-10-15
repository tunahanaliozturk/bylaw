import json
from collections.abc import Callable

import anthropic
import httpx2
import openai
import pytest

from bylaw.engine import ReviewError, make_reviewer
from bylaw.engine_anthropic import AnthropicReviewer
from bylaw.engine_openai import OpenAIReviewer

REVIEW = {
    "findings": [
        {
            "file": "users.py",
            "line_start": 7,
            "line_end": 7,
            "category": "security",
            "severity": "high",
            "message": "SQL built from a string.",
            "suggestion": None,
            "evidence": "CONTRIBUTING.md:3",
        }
    ],
    "criteria": [
        {
            "criterion": "issue#1/AC-1",
            "status": "met",
            "code": [{"file": "users.py", "line": 6}],
            "tests": [],
            "note": "",
        }
    ],
    "scope_creep": [],
}
SECRET = "sk-test-secret"  # noqa: S105 - a fake key the error message must not echo

Handler = Callable[[httpx2.Request], httpx2.Response]


def _anthropic(handler: Handler, model: str = "claude-opus-5-5") -> AnthropicReviewer:
    client = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    return AnthropicReviewer(model=model, effort="high", api_key=SECRET, http_client=client)


def _message(text: str, stop_reason: str = "end_turn") -> dict[str, object]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def test_anthropic_returns_a_review_and_asks_for_the_documented_settings() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=_message(json.dumps(REVIEW)))

    result = _anthropic(handler).review("system text", "user text")

    assert [f.evidence for f in result.findings] == ["CONTRIBUTING.md:3"]
    assert result.criteria[0].criterion == "issue#1/AC-1"
    body = json.loads(sent[0].content)
    assert body["model"] == "claude-opus-5-5"
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"]["effort"] == "high"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in sent[0].headers["anthropic-beta"]
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_models_without_server_side_fallback_do_not_ask_for_it() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=_message(json.dumps(REVIEW)))

    _anthropic(handler, model="claude-haiku-5-5").review("s", "u")

    assert "fallbacks" not in json.loads(sent[0].content)


@pytest.mark.parametrize(("stop_reason", "phrase"), [("refusal", "declined"), ("max_tokens", "ran out")])
def test_a_refusal_or_truncation_is_a_review_error(stop_reason: str, phrase: str) -> None:
    reviewer = _anthropic(lambda _request: httpx2.Response(200, json=_message("{", stop_reason)))

    with pytest.raises(ReviewError, match=phrase):
        reviewer.review("s", "u")


def test_an_api_error_never_shows_the_key() -> None:
    reviewer = _anthropic(
        lambda _request: httpx2.Response(
            401,
            json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}},
        )
    )

    with pytest.raises(ReviewError) as error:
        reviewer.review("s", "u")

    assert "401" in str(error.value)
    assert SECRET not in str(error.value)


def _response(text: str) -> dict[str, object]:
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "gpt-test",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "m1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }


def test_openai_returns_a_review_with_the_schema_and_effort() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=_response(json.dumps(REVIEW)))

    client = openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    result = OpenAIReviewer(model="gpt-test", effort="high", api_key=SECRET, http_client=client).review(
        "sys", "usr"
    )

    assert result.findings[0].severity == "high"
    body = json.loads(sent[0].content)
    assert (body["model"], body["instructions"], body["input"]) == ("gpt-test", "sys", "usr")
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["reasoning"] == {"effort": "high"}


def test_openai_needs_a_model_name() -> None:
    with pytest.raises(ReviewError, match="--model"):
        make_reviewer("openai", None, "high", SECRET)


def test_an_unknown_provider_is_a_review_error() -> None:
    with pytest.raises(ReviewError, match="provider"):
        make_reviewer("acme", None, "high", SECRET)
