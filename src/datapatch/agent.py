"""The auditable tool loop and the four experimental conditions."""
from __future__ import annotations

import json
import hashlib
import time
from typing import Callable

from .config import Settings
from .context import build_task_context
from .provider import BudgetExceeded, DeepSeekClient
from .review import review_candidate
from .workspace import Workspace, tool_definitions

MODES = ("baseline", "react", "context", "verified")
AGENT_REVISION = "v4.4-session-consistency"

SYSTEM_PROMPT = """You are DataPatch, an agent that implements data-engineering tickets in a local dbt/DuckDB project.
Use evidence from source models and live data, then make a minimal correct change. Never claim a fix without executing it.
You may only edit SQL files under the project's models/ directory. Preserve the requested output table, grain, column names,
and business rules. Do not alter tests, input data, profiles, or evaluation code. Reference solutions and final evaluation
are unavailable. The SQL query tool is read-only; use dbt to materialize model changes. A query can inspect information_schema.
Read the project's README or task instruction for the full business contract before editing.
Work from a concise checklist of requested changes and behavior that must be preserved. Tie every changed
filter, join, grouping and formula to the ticket or original SQL; do not invent exclusions or normalizations.
For an enumerated exclusion list, preserve the stated literal matching. Adding case conversion changes the
population unless the ticket or existing contract explicitly calls for it. Check observed values, including NULL.
Before computing a business metric, identify the authoritative source columns and their meaning. When a source
already contains a monetary total as well as quantity, price, discounts or taxes, inspect their relationship before
replacing that total with a derived gross amount. Compare the output to an independently aggregated source amount,
not only to another output expression using the same possibly mistaken formula. Check relationship keys and grain.
A non-NULL foreign key can still be an orphan. Inspect relationship_checks and anti-joins before choosing a
dimension join: verify lookup uniqueness, unmatched facts and alternate bridge relationships. Explain a trust
decision when two identifier paths disagree. Reconcile relevant fact quantities and monetary totals against the
output after aggregation; dimension coverage alone does not establish fact coverage.
Profiles describe full input tables: assess recoverability and lookup existence on the ticket's filtered facts.
For each requested metric or classification, check its input population, NULL behavior, date units, denominator,
boundary values and output grain. Validate the important clauses with targeted queries after materialization.
After building, use a compact SQL query to summarize requirement violations, including key coverage and uniqueness,
metric formulas and source populations where relevant. An empty checks directory supplies no semantic evidence.
Treat a reviewer finding as a claim to verify, not an instruction to rewrite a working expression.
When finished, provide a short Chinese handoff explaining the cause, change, verification and limitations.
All file paths are relative to the task workspace. Finish within the available call budget.
"""


class Agent:
    def __init__(self, workspace: Workspace, config: Settings, mode: str = "verified", emit: Callable[[dict], None] | None = None, client=None, focus_model: str | None = None):
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode}")
        self.workspace = workspace
        self.config = config
        self.mode = mode
        self.emit = emit or (lambda event: None)
        self.client = client or DeepSeekClient(config)
        self.focus_model = focus_model
        self.metrics = {"model_calls": 0, "tool_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0}

    def _response(self, messages: list[dict], tools: list[dict] | None) -> dict:
        if self.metrics["estimated_cost_usd"] >= self.config.run_budget_usd:
            raise BudgetExceeded("达到单任务估算费用上限，已停止模型调用")
        result = self.client.complete(messages, tools)
        self.metrics["model_calls"] += 1
        usage = result.get("usage", {})
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self.metrics[key] += int(usage.get(key, 0))
        self.metrics["estimated_cost_usd"] += result.get("estimated_cost_usd", 0)
        if result.get("finish_reason") == "length":
            self.metrics["output_limit_hits"] = self.metrics.get("output_limit_hits", 0) + 1
        self.emit({"type": "model", "name": result.get("model"), "content": result["message"].get("content") or "模型请求工具执行", "finish_reason": result.get("finish_reason"), "usage": usage, "response_id": result.get("response_id"), "latency_seconds": result.get("latency_seconds"), "budget": result.get("budget"), "metrics": dict(self.metrics)})
        return result

    def run(self, instruction: str) -> dict:
        started = time.monotonic()
        try:
            return self._run(instruction)
        except BudgetExceeded as exc:
            self.metrics["elapsed_seconds"] = round(time.monotonic() - started, 3)
            self.metrics["estimated_cost_usd"] = round(self.metrics["estimated_cost_usd"], 6)
            final = str(exc) + " 当前补丁是否正确，以随后独立构建和验收为准。"
            self.emit({"type": "final", "content": final, "stop_reason": "cost_limit", "metrics": dict(self.metrics)})
            return {"final_answer": final, "metrics": self.metrics, "stop_reason": "cost_limit", "model": self.config.model,
                    "agent_revision": AGENT_REVISION, "visible_validation": None,
                    "model_config": {"thinking_enabled": self.config.thinking_enabled, "reasoning_effort": self.config.reasoning_effort,
                                     "max_output_tokens": self.config.max_output_tokens}}

    def _run(self, instruction: str) -> dict:
        started = time.monotonic()
        initial_context = {"files": self.workspace.list_files(), "project_directory": str(self.workspace.project_dir.relative_to(self.workspace.root)).replace("\\", "/"), "database": self.workspace.database_path.name}
        if self.mode in {"context", "verified"}:
            initial_context["task_context"] = build_task_context(self.workspace, instruction, self.focus_model)
        if self.mode == "baseline":
            return self._single_patch(instruction, initial_context, started)
        prompt = SYSTEM_PROMPT
        if self.mode == "verified":
            prompt += "\nBefore handoff, execute build and check_contracts. Investigate counterexamples and repair failures within budget. For incremental models, consider a second run or full refresh when appropriate. Visible checks are necessary but not sufficient for correctness."
        messages = [{"role": "system", "content": prompt}, {"role": "user", "content": instruction + "\n\nWorkspace overview:\n" + json.dumps(initial_context, ensure_ascii=False, default=str)}]
        tools = tool_definitions(domain_tools=self.mode in {"context", "verified"}, validation_tools=self.mode == "verified")
        allowed_names = {tool["function"]["name"] for tool in tools}
        final = ""
        stop_reason = "step_limit"
        validation = None
        reads_since_write = 0
        reads_without_edit = 0
        observation_counts: dict[str, int] = {}
        candidate_review = None
        # Short guided repairs spend their small call allowance on a patch and
        # executable contracts; an optional second model pass needs more room.
        review_enabled = self.config.max_steps >= 6
        delivery_stage = False

        def review_once() -> dict:
            self.metrics["review_calls"] = self.metrics.get("review_calls", 0) + 1
            try:
                review = review_candidate(self.workspace, instruction, initial_context.get("task_context", {}), self._response)
            except BudgetExceeded:
                self.metrics["review_calls"] -= 1
                raise
            if review.get("skipped"):
                self.metrics["review_calls"] -= 1
            self.emit({"type": "review", "name": "candidate_semantic_review", "result": review, "metrics": dict(self.metrics)})
            messages.append({"role": "user", "content": "Candidate review is advisory. Check each finding against the full README and ticket. Only change code for a concrete requirement violation; reject hypothetical concerns or performance preferences that invent new requirements. Prefer keeping a working patch when a concern is unsupported.\n" + json.dumps(review, ensure_ascii=False)})
            return review

        for step in range(self.config.max_steps):
            remaining = self.config.max_steps - self.metrics["model_calls"]
            if remaining <= 0:
                break
            if self.mode == "verified" and not delivery_stage and remaining <= 6 and reads_without_edit >= 8 and hasattr(self.workspace, "diff") and not self.workspace.diff():
                delivery_stage = True
                self.metrics["delivery_stage_entries"] = self.metrics.get("delivery_stage_entries", 0) + 1
                messages.append({"role": "user", "content": "Exploration has used most of the budget without a candidate. Enter the delivery stage: write a scoped candidate SQL using the evidence already collected, then build/check it, or explain a concrete blocker. Read-only exploration tools are temporarily disabled until a model edit. This is a budget control, not permission to guess requirements."})
                self.emit({"type": "status", "name": "delivery_stage", "content": "预算收尾阶段：先提交候选补丁或说明阻塞，再验证。"})
            # Reserve time for the executor to act on review findings. The
            # reviewer consumes this same max_steps budget, once per run.
            if self.mode == "verified" and review_enabled and candidate_review is None and 2 <= remaining <= 4 and hasattr(self.workspace, "diff") and self.workspace.diff():
                candidate_review = review_once()
            if self.metrics["model_calls"] >= self.config.max_steps:
                break
            active_tools = [tool for tool in tools if not delivery_stage or tool["function"]["name"] in {"write_model", "run_dbt", "check_contracts"}]
            active_names = {tool["function"]["name"] for tool in active_tools}
            response = self._response(messages, active_tools)
            raw_message = response["message"]
            # Preserve reasoning_content for API providers requiring round-trip continuity;
            # do not expose hidden reasoning through the event log or UI.
            message = {key: value for key, value in raw_message.items() if key in {"role", "content", "tool_calls", "reasoning_content"} and value is not None}
            message.setdefault("role", "assistant")
            messages.append(message)
            calls = message.get("tool_calls", [])
            if response.get("finish_reason") == "length" and not calls:
                messages.append({"role": "user", "content": "The last response reached its output limit before delivery. Continue with a concise executable action or handoff. Do not treat truncation as completion."})
                continue
            if calls:
                for call in calls[:8]:
                    name = call["function"]["name"]
                    began = time.monotonic()
                    arguments = {}
                    try:
                        arguments = json.loads(call["function"].get("arguments", "{}"))
                        if name not in allowed_names or name not in active_names:
                            raise ValueError("该实验条件未启用此工具")
                        result = self.workspace.call(name, arguments)
                    except Exception as exc:
                        result = {"error": str(exc)[:3000], "error_type": type(exc).__name__}
                    self.metrics["tool_calls"] += 1
                    if name == "write_model" and "error" not in result:
                        delivery_stage = False
                        reads_since_write = 0
                        reads_without_edit = 0
                        observation_counts.clear()
                    elif name == "run_dbt" and result.get("success"):
                        reads_since_write = 0
                        observation_counts.clear()
                    elif name in {"list_files", "read_file", "query_sql", "search_schema", "get_lineage"}:
                        reads_since_write += 1
                        reads_without_edit += 1
                    if name == "query_sql" and "error" not in result:
                        # Compare observations rather than SQL text: equivalent
                        # COUNT queries can keep growing while returning no new evidence.
                        signature = json.dumps({key: result.get(key) for key in ("columns", "rows", "truncated")}, sort_keys=True, default=str)
                        observation_counts[signature] = observation_counts.get(signature, 0) + 1
                        if observation_counts[signature] == 3:
                            result = {**result, "progress_notice": "Three queries have returned the same observation since the last model edit. Consider whether further exploration adds evidence. Use the remaining budget to implement and validate the ticket, or clearly hand off a blocker."}
                            self.metrics["stagnation_notices"] = self.metrics.get("stagnation_notices", 0) + 1
                    self.emit({"type": "tool", "name": name, "step": step + 1, "arguments": arguments, "result": result, "elapsed_seconds": round(time.monotonic() - began, 3), "metrics": dict(self.metrics)})
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False, default=str)[:22000]})
                # Normally providers emit at most a handful of calls. Every call needs a reply.
                for call in calls[8:]:
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": '{"error":"Too many parallel calls; retry in a smaller batch"}'})
                remaining = self.config.max_steps - self.metrics["model_calls"]
                if (reads_since_write >= 8 and remaining > 2) or remaining in {4, 2}:
                    changed = bool(self.workspace.diff())
                    reminder = f"Execution budget: {remaining} model calls remain. Model files changed: {changed}. "
                    reminder += "Do not repeat semantically equivalent exploration. If sufficient evidence exists, implement the requested model change, run a targeted build and validate it. If blocked, explain the actual blocker."
                    messages.append({"role": "user", "content": reminder})
                    self.emit({"type": "status", "name": "progress_reminder", "content": reminder})
                    reads_since_write = 0
                continue
            final = message.get("content", "") or ""
            if self.mode == "verified":
                build = self.workspace.run_dbt("build")
                validation = self.workspace.check_contracts()
                self.metrics["tool_calls"] += 2
                self.metrics["handoff_gates"] = self.metrics.get("handoff_gates", 0) + 1
                self.emit({"type": "validation", "name": "handoff_gate", "result": {"build": build, "contracts": validation}})
                if not build["success"] or not validation["passed"]:
                    messages.append({"role": "user", "content": "交付前检查未通过。请依据这些可见执行反馈继续修复；不要声称已经成功：\n" + json.dumps({"build": build, "contracts": validation}, ensure_ascii=False, default=str)[:16000]})
                    final = ""
                    continue
                if review_enabled and candidate_review is None and self.metrics["model_calls"] < self.config.max_steps and hasattr(self.workspace, "diff") and self.workspace.diff():
                    candidate_review = review_once()
                    if candidate_review["verdict"] == "revise":
                        final = ""
                        continue
            stop_reason = "model_finished"
            break
        self.metrics["elapsed_seconds"] = round(time.monotonic() - started, 3)
        self.metrics["estimated_cost_usd"] = round(self.metrics["estimated_cost_usd"], 6)
        self.emit({"type": "final", "content": final or "已达到调用上限，请审阅最终独立验收结果。", "stop_reason": stop_reason, "metrics": dict(self.metrics)})
        if candidate_review and hasattr(self.workspace, "diff"):
            candidate_review["patch_changed_since_review"] = candidate_review.get("candidate_sha256") != hashlib.sha256(self.workspace.diff().encode()).hexdigest()
        return {"final_answer": final or "执行达到步数上限；补丁是否正确请查看独立验收，不能据此视为完成交付。", "metrics": self.metrics, "stop_reason": stop_reason, "visible_validation": validation, "candidate_review": candidate_review, "model": self.config.model, "model_config": {"thinking_enabled": self.config.thinking_enabled, "reasoning_effort": self.config.reasoning_effort, "max_output_tokens": self.config.max_output_tokens}, "agent_revision": AGENT_REVISION}

    def _single_patch(self, instruction: str, context: dict, started: float) -> dict:
        files = {}
        for path in self.workspace.list_files()["files"]:
            if path.endswith((".sql", ".md", ".yml")) and not path.startswith("checks/"):
                files[path] = self.workspace.read_file(path)["content"]
        context["source_files"] = files
        context["schema"] = self.workspace.search_schema()
        messages = [{"role": "system", "content": SYSTEM_PROMPT + '\nYou have one model call and no tools. Return ONLY JSON: {"files":[{"path":"models/...sql","content":"..."}],"explanation":"..."}.'}, {"role": "user", "content": instruction + "\n" + json.dumps(context, ensure_ascii=False, default=str)}]
        response = self._response(messages, None)
        content = response["message"].get("content", "")
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(cleaned)
        for patch in data.get("files", []):
            result = self.workspace.write_model(patch["path"], patch["content"])
            self.emit({"type": "tool", "name": "write_model", "arguments": patch, "result": result})
            self.metrics["tool_calls"] += 1
        self.metrics["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return {"final_answer": data.get("explanation", ""), "metrics": self.metrics, "stop_reason": "single_patch", "model": self.config.model}
