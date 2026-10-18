"""Providers beyond the Anthropic and OpenAI APIs, through fake transports: nothing leaves the machine."""

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import anthropic
import httpx2
import openai
import pytest

from bylaw import engine_anthropic
from bylaw.engine import ReviewError, Usage, can_review, make_reviewer
from bylaw.engine_anthropic import AnthropicReviewer
from bylaw.engine_openai import ChatReviewer
from tests.unit.test_engine import REVIEW, SECRET, _message, _streamed

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


def _claude(handler: Handler, provider: str, model: str | None = None) -> AnthropicReviewer:
    http = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(_streamed(handler)))
    reviewer = make_reviewer(provider, model, None, None, http_client=http)
    assert isinstance(reviewer, AnthropicReviewer)
    return reviewer


def _claude_replies(*texts: str) -> tuple[Handler, list[httpx2.Request]]:
    return _replies(*(httpx2.Response(200, json=_message(text)) for text in texts))


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Fake AWS credentials in the environment, and no AWS files of the machine running the tests."""
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")


@pytest.mark.usefixtures("aws")
def test_bedrock_signs_with_the_aws_credential_chain_and_asks_for_json() -> None:
    handler, sent = _claude_replies(json.dumps(REVIEW))

    result = _claude(handler, "bedrock").review("system text", "user text")

    assert result.criteria[0].criterion == "issue#1/AC-1"
    request = sent[0]
    assert (request.url.host, request.url.path) == (
        "bedrock-mantle.eu-west-1.api.aws",
        "/anthropic/v1/messages",
    )
    signature = request.headers["authorization"]
    assert signature.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "/eu-west-1/bedrock-mantle/aws4_request" in signature
    body = json.loads(request.content)
    assert body["model"] == "anthropic.claude-opus-5-5"
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "high"}
    assert "fallbacks" not in body
    assert "server-side-fallback" not in request.headers.get("anthropic-beta", "")
    assert body["system"][0]["text"].startswith("system text")
    assert '"scope_creep"' in body["system"][0]["text"]
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.usefixtures("aws")
def test_bedrock_asks_again_once_when_the_answer_is_not_a_review() -> None:
    handler, sent = _claude_replies("The change looks fine to me.", json.dumps(REVIEW))

    reviewer = _claude(handler, "bedrock")
    result = reviewer.review("s", "u")

    assert [f.evidence for f in result.findings] == ["CONTRIBUTING.md:3"]
    messages = json.loads(sent[1].content)["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[1]["content"] == "The change looks fine to me."
    assert "not a valid review" in messages[2]["content"]
    assert reviewer.last_usage == Usage(input_tokens=20, output_tokens=10)


@pytest.mark.usefixtures("aws")
def test_a_bedrock_answer_that_is_invalid_twice_is_a_review_error() -> None:
    handler, _ = _claude_replies("{}", "{}")

    with pytest.raises(ReviewError, match="not a valid review after one retry"):
        _claude(handler, "bedrock").review("s", "u")


def test_bedrock_sends_a_bedrock_api_key_as_a_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bedrock-api-key")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    handler, sent = _claude_replies(json.dumps(REVIEW))

    _claude(handler, "bedrock", "anthropic.claude-sonnet-5-5").review("s", "u")

    assert sent[0].headers["authorization"] == "Bearer bedrock-api-key"
    assert json.loads(sent[0].content)["model"] == "anthropic.claude-sonnet-5-5"


def test_bedrock_without_a_region_is_a_clear_review_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bedrock-api-key")

    with pytest.raises(ReviewError, match="AWS_REGION"):
        make_reviewer("bedrock", None, None, None)


@pytest.mark.usefixtures("aws")
def test_signing_for_bedrock_without_the_extra_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_anthropic, "find_spec", lambda name: None if name == "botocore" else name)

    with pytest.raises(ReviewError, match=r"bylaw\[bedrock\]"):
        make_reviewer("bedrock", None, None, None)


@pytest.mark.usefixtures("aws")
def test_a_bedrock_error_names_bedrock_and_the_status_only() -> None:
    denied = {"type": "error", "error": {"type": "permission_error", "message": f"denied for {SECRET}"}}
    handler, _ = _replies(httpx2.Response(403, json=denied))

    with pytest.raises(ReviewError) as error:
        _claude(handler, "bedrock").review("s", "u")

    assert str(error.value) == "Amazon Bedrock returned 403 (permission_error)"


@pytest.mark.usefixtures("aws")
def test_keys_for_other_providers_never_reach_bedrock(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "BYLAW_API_KEY"):
        monkeypatch.setenv(name, SECRET)
    handler, sent = _claude_replies(json.dumps(REVIEW))

    _claude(handler, "bedrock").review("s", "u")

    assert SECRET not in str(sent[0].headers)
