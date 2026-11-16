"""Frozen task lists, fair budgets, durable raw results, and descriptive statistics."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT, Settings
from .fixtures import list_tasks
from .service import RunService, write_json


def source_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted((ROOT / "src" / "datapatch").glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def summarize(records: list[dict]) -> list[dict]:
    summaries = []
    modes = list(dict.fromkeys(record["mode"] for record in records))
    for mode in modes:
        rows = [row for row in records if row["mode"] == mode]
        def delivered(row: dict) -> bool:
            return row.get("status") == "completed" and bool((row.get("final_build") or {}).get("success")) and bool((row.get("verification") or {}).get("passed"))
        passed = sum(delivered(row) for row in rows)
        n = len(rows)
        # Wilson interval: uncertainty, not a significance claim between small arms.
        z = 1.96
        p = passed / n if n else 0
        center = (p + z*z/(2*n)) / (1 + z*z/n) if n else 0
        spread = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1+z*z/n) if n else 0
        groups: dict[str, list[bool]] = {}
        for row in rows:
            groups.setdefault(row["task_id"], []).append(delivered(row))
        repeats = min((len(v) for v in groups.values()), default=0)
        summaries.append({
            "mode": mode, "trials": n, "passed": passed, "task_success_rate": round(p, 4),
            "wilson_95_interval": [round(max(0, center-spread), 4), round(min(1, center+spread), 4)],
            "all_repeats_success_rate": round(sum(all(v) for v in groups.values()) / len(groups), 4) if groups and repeats >= 2 else None,
            "min_repeats_per_task": repeats,
            "final_build_success_rate": round(sum(bool((row.get("final_build") or {}).get("success")) for row in rows)/n, 4) if n else 0,
            "model_calls": sum(row.get("metrics", {}).get("model_calls", 0) for row in rows),
            "tool_calls": sum(row.get("metrics", {}).get("tool_calls", 0) for row in rows),
            "total_tokens": sum(row.get("metrics", {}).get("total_tokens", 0) for row in rows),
            "estimated_cost_usd": round(sum(row.get("metrics", {}).get("estimated_cost_usd", 0) for row in rows), 6),
            "mean_elapsed_seconds": round(statistics.mean(row.get("metrics", {}).get("elapsed_seconds", 0) for row in rows), 2),
            "infrastructure_failures": sum(row["status"] == "failed" for row in rows),
        })
    return summaries


def evaluate(modes: list[str], task_ids: list[str] | None = None, repeats: int = 1, workers: int = 1, max_steps: int = 12, name: str | None = None) -> dict:
    settings = Settings.load()
    service = RunService(settings)
    if not settings.api_key:
        raise ValueError("真实评测需要 .env 中的 DEEPSEEK_API_KEY")
    task_ids = task_ids or [task["id"] for task in list_tasks() if task["split"] == "holdout"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = name or f"synthetic_{timestamp}"
    path = settings.artifacts_dir / "evaluations" / f"{name}.json"
    jobs = [{"task_id": task_id, "mode": mode, "repeat": repeat} for repeat in range(repeats) for task_id in task_ids for mode in modes]
    report = {
        "name": name, "title": "DataPatch 实际模型评测 · " + name, "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "datapatch-synthetic-v1", "provenance": "自建合成零售数据；holdout 是相同问题类型的新数据，非第三方榜单或未知任务泛化证明",
        "protocol": {"task_ids": task_ids, "modes": modes, "repeats": repeats, "workers": workers, "max_steps": max_steps, "model": settings.model, "temperature": None if settings.thinking_enabled else 0, "thinking_enabled": settings.thinking_enabled, "reasoning_effort": settings.reasoning_effort, "max_output_tokens": settings.max_output_tokens, "source_sha256": source_digest(), "cost_is_estimate": True, "input_usd_per_million": settings.input_rate, "output_usd_per_million": settings.output_rate, "aggregate_budget_usd": settings.eval_budget_usd, "hidden_feedback_to_agent": False},
        "status": "running", "planned_trials": len(jobs), "records": [], "summary": [],
    }
    # Freeze protocol before the first request. Every trial remains in the denominator.
    write_json(path, report)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as pool:
        pending = {}
        queue = iter(jobs)
        spent = 0.0
        for _ in range(min(workers, len(jobs))):
            job = next(queue, None)
            if job:
                future = pool.submit(service.run_sync, job["task_id"], job["mode"], max_steps)
                pending[future] = job
        while pending:
            finished = next(as_completed(pending))
            job = pending.pop(finished)
            try:
                record = finished.result()
            except Exception as exc:
                record = {"task_id": job["task_id"], "mode": job["mode"], "status": "failed", "error": str(exc), "metrics": {}}
            record["repeat"] = job["repeat"]
            report["records"].append(record)
            spent += record.get("metrics", {}).get("estimated_cost_usd", 0)
            report["summary"] = summarize(report["records"])
            write_json(path, report)
            success = bool((record.get("verification") or {}).get("passed"))
            print(f"[{len(report['records'])}/{len(jobs)}] {job['task_id']} {job['mode']} passed={success} estimated_usd={spent:.4f}", flush=True)
            if spent < settings.eval_budget_usd:
                following = next(queue, None)
                if following:
                    future = pool.submit(service.run_sync, following["task_id"], following["mode"], max_steps)
                    pending[future] = following
    report["status"] = "completed" if len(report["records"]) == len(jobs) else "budget_stopped"
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(path, report)
    render_report(report, path.with_suffix(".md"))
    return report


def render_report(report: dict, path: Path) -> None:
    lines = [f"# {report['title']}", "", f"数据集：{report['dataset']}", "", str(report.get("provenance", "")), "", f"状态：{report['status']}；记录 {len(report['records'])}/{report.get('planned_trials', len(report['records']))} 次实际运行。", "", "| 模式 | 成功/运行 | 成功率 | 三次/多次全成功 | 平均秒数 | Tokens | 估算 USD |", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in report["summary"]:
        consistency = row.get("all_repeats_success_rate")
        lines.append(f"| {row['mode']} | {row['passed']}/{row['trials']} | {row['task_success_rate']:.1%} | {consistency if consistency is not None else '未做重复实验'} | {row['mean_elapsed_seconds']} | {row['total_tokens']} | {row['estimated_cost_usd']} |")
    lines += ["", "费用为配置单价估算，实际账单以 API 服务商为准。小样本区间与原始失败保留在 JSON 中；没有证据时不宣称统计显著提升。", "", "## 逐次运行", "", "| 任务 | 模式 | 重复 | 成功 | Run ID |", "|---|---|---:|---|---|"]
    for row in report["records"]:
        lines.append(f"| {row['task_id']} | {row['mode']} | {row.get('repeat', 0)} | {bool((row.get('verification') or {}).get('passed'))} | {row.get('run_id', '')} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

