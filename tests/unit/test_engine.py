import json
from collections.abc import Callable

import anthropic
import httpx2
import openai
import pytest

from bylaw.engine import ReviewError, Usage, api_key_for, make_reviewer
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
            "text": None,
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
    client = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(_streamed(handler)))
    return AnthropicReviewer(model=model, effort="high", api_key=SECRET, http_client=client)


def _streamed(handler: Handler) -> Handler:
    """Serve a canned message as server-sent events when the request asks to stream, as the API does."""

    def serve(request: httpx2.Request) -> httpx2.Response:
        response = handler(request)
        if response.status_code != 200 or not json.loads(request.content).get("stream"):
            return response
        return httpx2.Response(
            200, content=_sse(json.loads(response.content)), headers={"content-type": "text/event-stream"}
        )

    return serve


def _sse(message: dict[str, object]) -> bytes:
    usage = dict(message["usage"])  # type: ignore[call-overload]
    start = {**message, "content": [], "stop_reason": None, "usage": {**usage, "output_tokens": 0}}
    events: list[tuple[str, object]] = [("message_start", {"type": "message_start", "message": start})]
    blocks: list[dict[str, str]] = message["content"]  # type: ignore[assignment]
    for index, block in enumerate(blocks):
        events += [
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "text_delta", "text": block["text"]},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": index}),
        ]
    delta = {"stop_reason": message["stop_reason"], "stop_sequence": None}
    events += [
        (
            "message_delta",
            {"type": "message_delta", "delta": delta, "usage": {"output_tokens": usage["output_tokens"]}},
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode("utf-8")


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


def test_an_openai_error_names_the_status_and_type_but_not_the_message() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        error = {
            "message": "Incorrect API key provided: sk-ant-a***wxyz",
            "type": "invalid_request_error",
            "code": "invalid_api_key",
        }
        return httpx2.Response(401, json={"error": error})

    client = openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    reviewer = OpenAIReviewer(model="gpt-test", effort=None, api_key=SECRET, http_client=client)

    with pytest.raises(ReviewError) as error:
        reviewer.review("s", "u")

    assert str(error.value) == "OpenAI API returned 401 (invalid_api_key)"


def test_an_anthropic_error_names_the_status_and_type_only() -> None:
    body = {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}
    reviewer = _anthropic(lambda _request: httpx2.Response(401, json=body))

    with pytest.raises(ReviewError) as error:
        reviewer.review("s", "u")

    assert str(error.value) == "Anthropic API returned 401 (authentication_error)"


def test_any_other_sdk_failure_is_a_review_error(monkeypatch: pytest.MonkeyPatch) -> None:
    reviewer = _anthropic(lambda _request: httpx2.Response(500))

    def boom(**_kwargs: object) -> None:
        raise ValueError("the SDK refused the parameters")

    monkeypatch.setattr(reviewer._client.beta.messages, "stream", boom)

    with pytest.raises(ReviewError, match="rejected the request"):
        reviewer.review("s", "u")


def test_the_provider_key_wins_over_the_shared_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYLAW_API_KEY", "shared")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-own")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert api_key_for("openai") == "openai-own"
    assert api_key_for("anthropic") == "shared"


def test_anthropic_reports_the_tokens_it_used_with_cache_counted_as_input() -> None:
    message = _message(json.dumps(REVIEW))
    message["usage"] = {
        "input_tokens": 1200,
        "output_tokens": 300,
        "cache_read_input_tokens": 800,
        "cache_creation_input_tokens": 0,
    }
    reviewer = _anthropic(lambda _: httpx2.Response(200, json=message))

    reviewer.review("system text", "user text")

    assert reviewer.last_usage == Usage(input_tokens=2000, output_tokens=300)


def test_openai_reports_the_tokens_it_used() -> None:
    response = _response(json.dumps(REVIEW))
    response["usage"] = {
        "input_tokens": 900,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 250,
        "output_tokens_details": {"reasoning_tokens": 100},
        "total_tokens": 1150,
    }
    client = openai.DefaultHttpxClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=response))
    )
    reviewer = OpenAIReviewer(model="gpt-test", effort=None, api_key=SECRET, http_client=client)

    reviewer.review("system text", "user text")

    assert reviewer.last_usage == Usage(input_tokens=900, output_tokens=250)


def test_usage_from_an_earlier_review_is_not_reported_again() -> None:
    with_usage = _response(json.dumps(REVIEW))
    with_usage["usage"] = {
        "input_tokens": 900,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 250,
        "output_tokens_details": {"reasoning_tokens": 100},
        "total_tokens": 1150,
    }
    replies = iter([with_usage, _response(json.dumps(REVIEW))])
    client = openai.DefaultHttpxClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=next(replies)))
    )
    reviewer = OpenAIReviewer(model="gpt-test", effort=None, api_key=SECRET, http_client=client)

    reviewer.review("system text", "user text")
    reviewer.review("system text", "user text")

    assert reviewer.last_usage is None


def test_a_refused_review_still_reports_the_tokens_it_was_billed() -> None:
    reviewer = _anthropic(lambda _request: httpx2.Response(200, json=_message("{", "refusal")))

    with pytest.raises(ReviewError):
        reviewer.review("s", "u")

    assert reviewer.last_usage == Usage(input_tokens=10, output_tokens=5)


def test_openai_is_asked_not_to_store_the_review() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=_response(json.dumps(REVIEW)))

    client = openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    OpenAIReviewer(model="gpt-test", effort=None, api_key=SECRET, http_client=client).review("s", "u")

    assert json.loads(sent[0].content)["store"] is False


def test_a_truncated_openai_answer_still_reports_the_tokens_it_was_billed() -> None:
    cut = _response('{"findings": [')
    cut["status"] = "incomplete"
    cut["incomplete_details"] = {"reason": "max_output_tokens"}
    cut["usage"] = {
        "input_tokens": 700,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 4000,
        "output_tokens_details": {"reasoning_tokens": 3000},
        "total_tokens": 4700,
    }
    client = openai.DefaultHttpxClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=cut))
    )
    reviewer = OpenAIReviewer(model="gpt-test", effort=None, api_key=SECRET, http_client=client)

    with pytest.raises(ReviewError):
        reviewer.review("s", "u")

    assert reviewer.last_usage == Usage(input_tokens=700, output_tokens=4000)


def test_anthropic_streams_with_room_for_a_long_review() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=_message(json.dumps(REVIEW)))

    result = _anthropic(handler).review("system text", "user text")

    body = json.loads(sent[0].content)
    assert (body["stream"], body["max_tokens"]) == (True, 64000)
    assert result.criteria[0].criterion == "issue#1/AC-1"
