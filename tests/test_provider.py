"""Provider contract tests use only an in-process HTTP transport."""
import json

import httpx
import pytest

from datapatch.config import Settings
from datapatch.provider import DeepSeekClient, ModelError
import datapatch.provider as provider_module


@pytest.fixture
def mock_api(monkeypatch):
    requests = []
    payload = {
        "id": "mock-response",
        "model": "deepseek-flash",
        "choices": [{
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": "Mock handoff",
                "reasoning_content": "Synthetic test reasoning",
            },
        }],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 200,
            "total_tokens": 300,
            "completion_tokens_details": {"reasoning_tokens": 150},
        },
    }

    def handle(request):
        assert request.method == "POST"
        assert request.url == httpx.URL("https://provider.test/chat/completions")
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=payload)

    original_client = httpx.Client
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(
        provider_module.httpx,
        "Client",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    return requests, payload


@pytest.mark.parametrize("effort,output_limit", [("high", 16384), ("max", 32768)])
def test_thinking_request_preserves_effort_and_output_budget(mock_api, effort, output_limit):
    requests, _ = mock_api
    settings = Settings(
        api_key="unit-test-key",
        base_url="https://provider.test",
        model="deepseek-flash",
        thinking_enabled=True,
        reasoning_effort=effort,
        max_output_tokens=output_limit,
    )
    tools = [{"type": "function", "function": {"name": "query_sql", "parameters": {"type": "object"}}}]
    messages = [{"role": "user", "content": "Inspect the report"}]

    DeepSeekClient(settings).complete(messages, tools)

    assert len(requests) == 1
    request = requests[0]
    assert request["model"] == "deepseek-flash"
    assert request["thinking"] == {"type": "enabled"}
    assert request["reasoning_effort"] == effort
    assert request["max_tokens"] == output_limit
    assert "temperature" not in request
    assert request["messages"] == messages
    assert request["tools"] == tools


def test_nonthinking_flash_keeps_legacy_request_compatibility(mock_api):
    requests, _ = mock_api
    settings = Settings(
        api_key="unit-test-key",
        base_url="https://provider.test",
        model="deepseek-flash",
        thinking_enabled=False,
        max_output_tokens=3000,
        input_rate=0.30,
        output_rate=1.20,
    )

    DeepSeekClient(settings).complete([{"role": "user", "content": "Repair SQL"}])

    assert len(requests) == 1
    request = requests[0]
    assert request["model"] == "deepseek-flash"
    assert request["thinking"] == {"type": "disabled"}
    assert request["max_tokens"] == 3000
    assert request["temperature"] == 0
    assert "reasoning_effort" not in request
    assert "tools" not in request


def test_reasoning_usage_is_preserved_without_double_counting_output_cost(mock_api):
    _, payload = mock_api
    payload["choices"][0]["finish_reason"] = "length"
    settings = Settings(
        api_key="unit-test-key",
        base_url="https://provider.test",
        input_rate=0.30,
        output_rate=1.20,
    )

    response = DeepSeekClient(settings).complete([{"role": "user", "content": "Repair SQL"}])

    # The API's 200 completion tokens already include the 150 reasoning tokens.
    assert response["usage"] == payload["usage"]
    assert response["estimated_cost_usd"] == pytest.approx((100 * 0.30 + 200 * 1.20) / 1_000_000)
    assert response["finish_reason"] == "length"
    assert response["message"]["reasoning_content"] == "Synthetic test reasoning"
    assert response["response_id"] == "mock-response"


def test_pro_is_rejected_before_http_even_when_set_directly(mock_api):
    requests, _ = mock_api
    with pytest.raises(ModelError, match="禁止使用 Pro"):
        DeepSeekClient(Settings(api_key="unit-test-key", model="deepseek-v4-pro"))
    assert not requests


def test_budget_is_checked_before_the_next_request(mock_api):
    requests, _ = mock_api
    client = DeepSeekClient(Settings(api_key="unit-test-key", base_url="https://provider.test", run_budget_usd=0.00001))
    with pytest.raises(ModelError, match="调用 API 前停止"):
        client.complete([{"role": "user", "content": "Repair SQL"}])
    assert not requests


def test_output_allowance_reduces_before_budget_would_be_exceeded(mock_api):
    requests, _ = mock_api
    client = DeepSeekClient(Settings(api_key="unit-test-key", base_url="https://provider.test", run_budget_usd=0.003))
    result = client.complete([{"role": "user", "content": "Repair SQL"}])
    assert 512 <= requests[0]["max_tokens"] < 8192
    assert result["budget"]["reserved_estimate_usd"] <= 0.003
    client.spent_usd = 0.00299
    with pytest.raises(ModelError, match="调用 API 前停止"):
        client.complete([{"role": "user", "content": "Repair SQL"}])
    assert len(requests) == 1


def test_ambiguous_timeout_is_not_automatically_retried(monkeypatch):
    calls = []
    original_client = httpx.Client

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("mock timeout", request=request)

    monkeypatch.setattr(provider_module.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(timeout), **kwargs))
    with pytest.raises(ModelError, match="未自动重试"):
        DeepSeekClient(Settings(api_key="unit-test-key")).complete([{"role": "user", "content": "Repair SQL"}])
    assert len(calls) == 1
