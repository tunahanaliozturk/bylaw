"""Providers beyond the Anthropic and OpenAI APIs, through fake transports: nothing leaves the machine."""

import json
from collections.abc import Callable, Iterator

import httpx2
import openai
import pytest

from bylaw.engine import ReviewError, Usage, can_review, make_reviewer
from bylaw.engine_openai import ChatReviewer
from tests.unit.test_engine import REVIEW, SECRET

Handler = Callable[[httpx2.Request], httpx2.Response]
LOCAL = "http://localhost:11434/v1"
# Every variable that holds a key for some provider; a test that sets them all proves none of them travels
# to a provider it was not meant for.
FOREIGN_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "BYLAW_API_KEY",
    "AWS_BEARER_TOKEN_BEDROCK",
    "ANTHROPIC_AWS_API_KEY",
    "ANTHROPIC_FOUNDRY_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_AD_TOKEN",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        *FOREIGN_KEYS,
        "OPENAI_BASE_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "ANTHROPIC_BEDROCK_MANTLE_BASE_URL",
        "CLOUD_ML_REGION",
        "ANTHROPIC_VERTEX_PROJECT_ID",
        "ANTHROPIC_VERTEX_BASE_URL",
        "ANTHROPIC_FOUNDRY_RESOURCE",
        "ANTHROPIC_FOUNDRY_BASE_URL",
        "AZURE_OPENAI_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)


def _chat(text: str | None, finish: str = "stop", tokens: tuple[int, int] = (10, 5)) -> dict[str, object]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "qwen3:4b",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1], "total_tokens": sum(tokens)},
    }


def _replies(*replies: httpx2.Response) -> tuple[Handler, list[httpx2.Request]]:
    sent: list[httpx2.Request] = []
    queue: Iterator[httpx2.Response] = iter(replies)

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return next(queue)

    return handler, sent


def _local(handler: Handler, model: str = "qwen3:4b") -> ChatReviewer:
    reviewer = make_reviewer(
        "openai-compatible",
        model,
        None,
        None,
        LOCAL,
        http_client=openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    assert isinstance(reviewer, ChatReviewer)
    return reviewer


def _ok(text: str, tokens: tuple[int, int] = (10, 5)) -> httpx2.Response:
    return httpx2.Response(200, json=_chat(text, tokens=tokens))


def test_openai_compatible_asks_the_base_url_for_a_strict_schema_and_returns_the_review() -> None:
    handler, sent = _replies(_ok(json.dumps(REVIEW)))

    result = _local(handler).review("system text", "user text")

    assert result.criteria[0].criterion == "issue#1/AC-1"
    assert str(sent[0].url) == f"{LOCAL}/chat/completions"
    body = json.loads(sent[0].content)
    assert body["model"] == "qwen3:4b"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    system = body["messages"][0]
    assert system["role"] == "system"
    assert system["content"].startswith("system text")
    assert '"findings"' in system["content"]


def test_a_server_that_rejects_structured_output_is_asked_for_plain_json() -> None:
    rejected = httpx2.Response(400, json={"error": {"message": "response_format is not supported"}})
    handler, sent = _replies(rejected, _ok(json.dumps(REVIEW)))

    result = _local(handler).review("s", "u")

    assert [f.evidence for f in result.findings] == ["CONTRIBUTING.md:3"]
    assert "response_format" not in json.loads(sent[1].content)
    assert "JSON" in json.loads(sent[1].content)["messages"][0]["content"]


def test_an_invalid_answer_is_asked_again_once_with_what_was_wrong() -> None:
    wrong = json.loads(json.dumps(REVIEW))
    wrong["findings"][0]["severity"] = "urgent"
    handler, sent = _replies(_ok(json.dumps(wrong), (100, 20)), _ok(json.dumps(REVIEW), (150, 30)))

    reviewer = _local(handler)
    result = reviewer.review("s", "u")

    assert result.findings[0].severity == "high"
    retry = json.loads(sent[1].content)["messages"]
    assert retry[2] == {"role": "assistant", "content": json.dumps(wrong)}
    assert retry[3]["role"] == "user"
    assert "findings.0.severity" in retry[3]["content"]
    assert reviewer.last_usage == Usage(input_tokens=250, output_tokens=50)


def test_an_answer_that_is_invalid_twice_is_a_clear_review_error() -> None:
    handler, sent = _replies(_ok("I think the change is fine."), _ok('{"findings": []}'))

    with pytest.raises(ReviewError, match=r"not a valid review after one retry.*criteria"):
        _local(handler).review("s", "u")

    assert len(sent) == 2


def test_an_answer_wrapped_in_prose_and_a_code_fence_is_still_read() -> None:
    handler, _ = _replies(_ok(f"Here is the review:\n```json\n{json.dumps(REVIEW)}\n```\n"))

    result = _local(handler).review("s", "u")

    assert result.criteria[0].status == "met"


def test_a_review_error_never_repeats_what_the_model_wrote() -> None:
    planted = {**REVIEW, "@octocat::error::": 1}
    handler, _ = _replies(_ok(json.dumps(planted)), _ok(json.dumps(planted)))

    with pytest.raises(ReviewError) as error:
        _local(handler).review("s", "u")

    assert "@octocat" not in str(error.value)
    assert "::" not in str(error.value)


def test_a_local_answer_cut_off_by_the_token_limit_is_a_review_error() -> None:
    handler, _ = _replies(httpx2.Response(200, json=_chat('{"findings": [', finish="length")))

    with pytest.raises(ReviewError, match="ran out of output tokens"):
        _local(handler).review("s", "u")


def test_a_local_server_error_names_the_status_only() -> None:
    handler, _ = _replies(httpx2.Response(404, json={"error": {"message": f"model {SECRET} not found"}}))

    with pytest.raises(ReviewError) as error:
        _local(handler).review("s", "u")

    assert "404" in str(error.value)
    assert SECRET not in str(error.value)


def test_openai_compatible_needs_a_base_url_and_a_model() -> None:
    with pytest.raises(ReviewError, match="--base-url"):
        make_reviewer("openai-compatible", "qwen3:4b", None, None)
    with pytest.raises(ReviewError, match="--model"):
        make_reviewer("openai-compatible", None, None, None, LOCAL)


def test_a_base_url_is_only_for_the_openai_compatible_provider() -> None:
    with pytest.raises(ReviewError, match="--base-url"):
        make_reviewer("openai", "gpt-test", None, SECRET, LOCAL)


def test_openai_compatible_sends_only_its_own_key_and_never_the_openai_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    handler, sent = _replies(_ok(json.dumps(REVIEW)), _ok(json.dumps(REVIEW)))

    _local(handler).review("s", "u")
    make_reviewer(
        "openai-compatible",
        "m",
        None,
        "local-key",
        LOCAL,
        http_client=openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    ).review("s", "u")

    assert SECRET not in sent[0].headers.get("authorization", "")
    assert sent[1].headers["authorization"] == "Bearer local-key"


def test_the_effort_goes_to_a_local_server_as_reasoning_effort() -> None:
    handler, sent = _replies(_ok(json.dumps(REVIEW)))
    reviewer = make_reviewer(
        "openai-compatible",
        "gpt-oss:20b",
        "low",
        None,
        LOCAL,
        http_client=openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )

    reviewer.review("s", "u")

    assert json.loads(sent[0].content)["reasoning_effort"] == "low"


def test_a_local_server_needs_no_key_to_review() -> None:
    assert can_review("openai-compatible")
    assert not can_review("openai")
