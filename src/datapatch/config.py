"""Configuration stays on the server; no credentials are returned to the UI."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    max_steps: int = 12
    max_output_tokens: int = 8192
    thinking_enabled: bool = True
    reasoning_effort: str = "high"
    request_timeout: float = 300
    input_rate: float = 0.30
    output_rate: float = 1.20
    run_budget_usd: float = 0.125
    eval_budget_usd: float = 0.50
    artifacts_dir: Path = ROOT / "artifacts"

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(ROOT / ".env", override=False)
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
        if model != "deepseek-flash":
            raise ValueError("本项目只允许 deepseek-flash；请修改 DEEPSEEK_MODEL，禁止使用 Pro。")
        # Conservative peak, cache-miss estimates; rates can be overridden.
        input_default, output_default = "0.30", "1.20"
        effort = os.getenv("DEEPSEEK_REASONING_EFFORT", "high")
        if effort not in {"low", "high", "max"}:
            raise ValueError("DEEPSEEK_REASONING_EFFORT must be low, high or max")
        return cls(
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            model=model,
            max_steps=int(os.getenv("DATAPATCH_MAX_STEPS", "12")),
            max_output_tokens=int(os.getenv("DATAPATCH_MAX_OUTPUT_TOKENS", "8192")),
            thinking_enabled=os.getenv("DEEPSEEK_THINKING", "enabled").lower() == "enabled",
            reasoning_effort=effort,
            request_timeout=float(os.getenv("DATAPATCH_REQUEST_TIMEOUT", "300")),
            input_rate=float(os.getenv("DATAPATCH_INPUT_USD_PER_MILLION", input_default)),
            output_rate=float(os.getenv("DATAPATCH_OUTPUT_USD_PER_MILLION", output_default)),
            run_budget_usd=float(os.getenv("DATAPATCH_RUN_BUDGET_USD", "0.125")),
            eval_budget_usd=float(os.getenv("DATAPATCH_EVAL_BUDGET_USD", "0.50")),
            artifacts_dir=Path(os.getenv("DATAPATCH_ARTIFACTS", str(ROOT / "artifacts"))),
        )

