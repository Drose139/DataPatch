"""Flash-only HTTP adapter with usage records and a pre-request cost allowance."""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .config import Settings


class ModelError(RuntimeError):
    pass


class BudgetExceeded(ModelError):
    """An expected local stop before HTTP, distinct from a provider failure."""


class DeepSeekClient:
    def __init__(self, settings: Settings):
        if not settings.api_key:
            raise ModelError("尚未配置 DEEPSEEK_API_KEY。请填写项目根目录的 .env。")
        self.settings = settings
        self.spent_usd = 0.0
        self._check_model()

    def _check_model(self) -> None:
        if self.settings.model != "deepseek-flash":
            raise ModelError("本项目只允许 deepseek-flash，禁止使用 Pro。")

    def _output_allowance(self, messages: list[dict], tools: list[dict] | None) -> tuple[int, float]:
        s = self.settings
        # UTF-8 bytes plus generous framing overhead bound the normal BPE input
        # conservatively. This is an estimate, not the provider's billing meter.
        input_bound = len(json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False).encode("utf-8")) + 256 * len(messages) + 4096
        input_cost = input_bound * max(s.input_rate, 0.30) / 1_000_000
        output_rate = max(s.output_rate, 1.20)
        remaining = s.run_budget_usd - self.spent_usd
        allowance = min(s.max_output_tokens, int(max(0, remaining - input_cost) * 1_000_000 / output_rate))
        if allowance < 512:
            raise BudgetExceeded("剩余单任务估算预算不足以发送下一次请求，已在调用 API 前停止。")
        return allowance, input_cost + allowance * output_rate / 1_000_000

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict[str, Any]:
        s = self.settings
        self._check_model()
        output_allowance, reserved_estimate = self._output_allowance(messages, tools)
        body: dict[str, Any] = {
            "model": s.model,
            "messages": messages,
            "max_tokens": output_allowance,
            "thinking": {"type": "enabled" if s.thinking_enabled else "disabled"},
        }
        if s.thinking_enabled:
            body["reasoning_effort"] = s.reasoning_effort
        else:
            body["temperature"] = 0
        if tools:
            body["tools"] = tools
        started = time.monotonic()
        with httpx.Client(timeout=s.request_timeout) as client:
            try:
                response = client.post(
                    f"{s.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {s.api_key}"},
                    json=body,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                # A timed-out generation may already have been billed. Never
                # silently repeat a paid request with an unknown outcome.
                raise ModelError(f"模型网络请求失败：{type(exc).__name__}；未自动重试，费用可能未记录。") from None
            if response.is_error:
                detail = response.text[:500].replace(s.api_key, "[REDACTED]")
                raise ModelError(f"模型 API HTTP {response.status_code}: {detail}")
            data = response.json()
            if not data.get("choices"):
                raise ModelError("模型 API 未返回 choices")
            usage = data.get("usage", {})
            prompt = int(usage.get("prompt_tokens", 0))
            completion = int(usage.get("completion_tokens", 0))
            cost = (prompt * max(s.input_rate, 0.30) + completion * max(s.output_rate, 1.20)) / 1_000_000
            self.spent_usd += cost
            return {
                "message": data["choices"][0]["message"],
                "finish_reason": data["choices"][0].get("finish_reason"),
                "model": data.get("model", s.model),
                "response_id": data.get("id"),
                "usage": usage,
                "estimated_cost_usd": cost,
                "budget": {"request_max_output_tokens": output_allowance, "reserved_estimate_usd": reserved_estimate,
                           "spent_estimate_usd": self.spent_usd, "run_limit_usd": s.run_budget_usd},
                "latency_seconds": round(time.monotonic() - started, 3),
            }
