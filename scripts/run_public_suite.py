"""Run one explicitly selected Flash-only public development round, sequentially.

This command never retries a task, starts another round, or resumes a partially
used workspace. Prepare the pinned benchmark inputs before invoking it.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from datapatch.config import ROOT, Settings
from datapatch.evaluation import render_report, source_digest, summarize

_spec = importlib.util.spec_from_file_location("public_suite_adapter", ROOT / "integrations/harbor_agent.py")
adapter = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(adapter)

MAX_STEPS = 12
TASK_BUDGET_USD = 0.125
ALLOWED_MODEL = "deepseek-flash"
TASK_NAMES = {
    "dbt-fix-refund-reconciliation": "refund",
    "dbt-fix-division-by-zero": "division",
    "dbt-fix-inventory-model": "inventory",
    "dbt-fix-product-metrics": "product",
}


def _flash_settings() -> Settings:
    settings = Settings.load()
    if settings.model != ALLOWED_MODEL:
        raise ValueError("This runner permits only deepseek-flash; configure DEEPSEEK_MODEL before running")
    expected = {"thinking_enabled": True, "reasoning_effort": "high", "max_output_tokens": 8192,
                "input_rate": 0.30, "output_rate": 1.20}
    mismatches = [key for key, value in expected.items() if getattr(settings, key) != value]
    if mismatches:
        raise ValueError("Flash suite settings do not match its fixed protocol: " + ", ".join(mismatches))
    return settings


def _write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render_report(report, path.with_suffix(".md"))
    with path.with_suffix(".md").open("a", encoding="utf-8") as stream:
        for row in report.get("records", []):
            raw = row.get("raw_verifier") or {}
            if raw.get("stdout"):
                stream.write("\n### " + row["task_id"] + " 原始 pytest\n\n```text\n" + raw["stdout"] + "\n```\n")


def _failed_trial(path: Path, task: str, case: Path, protocol: dict, errors: list[dict], elapsed: float) -> None:
    """Keep the planned denominator even when local preparation/scoring fails."""
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    run_id = case.name + "-verified"
    row = {"run_id": run_id, "task_id": task, "mode": "verified", "repeat": 0, "status": "failed",
           "verification": {"passed": False, "reward": None, "components_passed": [], "components_failed": [], "valid_pytest_execution": False},
           "raw_verifier": {"mode": "unavailable", "stdout": "", "reason": "No independent pytest evidence was produced"},
           "final_build": {"success": False}, "stop_reason": "pipeline_exception", "final_answer": "",
           "model": ALLOWED_MODEL, "max_steps": MAX_STEPS, "budget_usd": TASK_BUDGET_USD,
           "metrics": {}, "metrics_available": False, "execution_error": json.dumps(errors, ensure_ascii=False),
           "failure_category": "pipeline_exception", "pipeline_elapsed_seconds": elapsed,
           "source_sha256": protocol["source_sha256"], "source_snapshot": protocol["source_snapshot"],
           "source_snapshot_sha256": protocol["source_snapshot_sha256"]}
    agent_path = ROOT / "external/native-results" / (run_id + ".json")
    if agent_path.is_file():
        try:
            agent = json.loads(agent_path.read_text(encoding="utf-8"))
            row["metrics"] = agent.get("result", {}).get("metrics", {})
            row["metrics_available"] = bool(row["metrics"])
            row["final_build"] = agent.get("final_build") or {"success": False}
            row["agent_report"] = str(agent_path)
        except (OSError, ValueError):
            pass
    verifier_path = ROOT / "external/public-verifiers" / task / (case.name + "-evaluation.json")
    if verifier_path.is_file():
        raw = json.loads(verifier_path.read_text(encoding="utf-8"))
        ordinary = raw.get("grading_protocol") == "pytest_exit_status"
        counts = raw.get("pytest_counts") or {}
        observed = counts.get("passed", 0) + counts.get("failed", 0) > 0 if ordinary else bool(raw.get("components_passed") or raw.get("components_failed"))
        executed = observed and bool(re.search(r"\b[1-9]\d* (?:passed|failed)\b[^\n]*\bin \d+(?:\.\d+)?s\b", raw.get("stdout", ""))) and raw.get("reward") is not None
        row.update({"raw_verifier": raw, "verifier_report": str(verifier_path),
                    "verification": {"passed": False, "reward": raw.get("reward"), "components_passed": raw.get("components_passed", []),
                                     "components_failed": raw.get("components_failed", []), "valid_pytest_execution": executed,
                                     "grading_protocol": raw.get("grading_protocol", "component_reward_json"), "pytest_counts": raw.get("pytest_counts")}})
    records = [item for item in report.get("records", []) if item["run_id"] != run_id] + [row]
    report.update({"name": path.stem, "title": "Flash public round: pipeline failure preserved", "status": "running",
                   "dataset": "snowflake-data-eng-bench/native-public-development-subset",
                   "records": records, "summary": summarize(records), "planned_trials": len(protocol["task_ids"]),
                   "protocol": {"planned_task_ids": protocol["task_ids"], "task_ids": protocol["task_ids"], "modes": ["verified"], "repeats": 1,
                                "source_sha256": protocol["source_sha256"]},
                   "limitations": report.get("limitations", []) + ["A pipeline exception interrupted this trial; unavailable usage must not be interpreted as zero billing."]})
    _write_report(report, path)


def run_suite(round_number: int, source_snapshot: Path, tasks: tuple[str, ...] | None = None, *, benchmark_snapshot: Path | None = None) -> dict:
    if round_number not in (1, 2):
        raise ValueError("Only explicit round 1 or 2 is permitted")
    selected = tuple(TASK_NAMES) if tasks is None else tuple(tasks)
    if not selected or len(selected) != len(set(selected)) or any(task not in TASK_NAMES for task in selected):
        raise ValueError("Choose a nonempty unique subset of the four fixed public tasks")
    settings = _flash_settings()
    source_snapshot = source_snapshot.resolve()
    with zipfile.ZipFile(source_snapshot) as archive:
        manifest = json.loads(archive.read("source-manifest.json"))
    current_hash = source_digest()
    if manifest.get("core_source_sha256") != current_hash:
        raise ValueError("Source snapshot does not match the current core")
    benchmark_snapshot = (benchmark_snapshot or ROOT / "external/data-eng-bench").resolve()
    name = f"v41_flash_round{round_number}_20261025"
    output = ROOT / "artifacts/evaluations" / (name + ".json")
    protocol_path = ROOT / "artifacts/protocols" / (name + ".json")
    result_root = ROOT / "external/native-results"
    evaluator_root = ROOT / "external/public-verifiers"
    cases = {task: ROOT / "external/native-cases" / f"{TASK_NAMES[task]}-v41-flash-r{round_number}" for task in selected}
    if output.exists() or output.with_suffix(".md").exists() or protocol_path.exists():
        raise ValueError("This round already has a protocol/report; it cannot be resumed or overwritten")
    for case in cases.values():
        prefix = result_root / (case.name + "-verified")
        if case.exists() or any(prefix.with_suffix(suffix).exists() for suffix in (".json", ".jsonl", ".patch")):
            raise ValueError(f"Existing case or result cannot be reused: {case.name}")
    protocol = {"name": name, "created_at": datetime.now(timezone.utc).isoformat(), "round": round_number,
                "task_ids": list(selected), "mode": "verified", "repeats": 1, "model": ALLOWED_MODEL,
                "max_steps": MAX_STEPS, "run_budget_usd": TASK_BUDGET_USD,
                "round_budget_usd": round(TASK_BUDGET_USD * len(selected), 3), "maximum_two_round_budget_usd": 1.0,
                "thinking_enabled": settings.thinking_enabled, "reasoning_effort": settings.reasoning_effort,
                "max_output_tokens": settings.max_output_tokens, "input_rate": settings.input_rate, "output_rate": settings.output_rate,
                "source_sha256": current_hash, "source_snapshot": str(source_snapshot),
                "source_snapshot_sha256": hashlib.sha256(source_snapshot.read_bytes()).hexdigest(),
                "upstream_commit": adapter.PINNED_COMMIT, "automatic_retries": False,
                "automatic_next_round": False, "verifier_feedback_to_solver": False,
                "case_directories": {task: str(case) for task, case in cases.items()}}
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    with protocol_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")
    for task, case in cases.items():
        errors = []
        began = time.monotonic()
        print(f"TASK {task}: prepare", flush=True)
        prepared = False
        try:
            adapter.prepare_native_case(benchmark_snapshot, case, task)
            prepared = True
        except Exception as exc:
            errors.append({"stage": "prepare", "type": type(exc).__name__, "error": str(exc)})
        if prepared:
            try:
                print(f"TASK {task}: run Flash (12 calls maximum)", flush=True)
                _flash_settings()  # Reject a configuration change to Pro before any new task.
                adapter.run_native_case(case, result_root, mode="verified", max_steps=MAX_STEPS,
                                        budget_usd=TASK_BUDGET_USD, source_snapshot=source_snapshot)
            except Exception as exc:
                errors.append({"stage": "run", "type": type(exc).__name__, "error": str(exc)})
        try:
            print(f"TASK {task}: independent pytest", flush=True)
            adapter.evaluate_native_case(case, evaluator_root)
        except Exception as exc:
            errors.append({"stage": "evaluate", "type": type(exc).__name__, "error": str(exc)})
        try:
            print(f"TASK {task}: render", flush=True)
            adapter.render_public_summary(case, result_root, evaluator_root, output, planned_tasks=selected, repeat=0, repeats=1)
        except Exception as exc:
            errors.append({"stage": "render", "type": type(exc).__name__, "error": str(exc)})
            _failed_trial(output, task, case, protocol, errors, round(time.monotonic() - began, 3))
        report = json.loads(output.read_text(encoding="utf-8"))
        for row in report["records"]:
            if row["run_id"] == case.name + "-verified":
                row["pipeline_errors"] = errors
                if row.get("execution_error"):
                    row["failure_category"] = "execution_error"
        report.update({"title": f"Flash 公开开发子集第 {round_number} 轮（非官方 Harbor 成绩）",
                       "status": "completed" if len(report["records"]) == len(selected) else "running",
                       "planned_trials": len(selected)})
        report["protocol"].update({"runner_protocol": str(protocol_path), "model": ALLOWED_MODEL,
                                    "max_steps": MAX_STEPS, "run_budget_usd": TASK_BUDGET_USD,
                                    "round_budget_usd": protocol["round_budget_usd"], "automatic_retries": False,
                                    "automatic_next_round": False, "hidden_feedback_to_agent": False})
        report["summary"] = summarize(report["records"])
        _write_report(report, output)
        print(f"TASK {task}: recorded; no retry", flush=True)
    return {"report": str(output), "protocol": str(protocol_path), "planned_trials": len(selected),
            "summary": report["summary"], "all_passed": all(row.get("verification", {}).get("passed") is True for row in report["records"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", type=int, choices=(1, 2), required=True, dest="round_number")
    parser.add_argument("--source-snapshot", type=Path, required=True)
    parser.add_argument("--task", action="append", choices=TASK_NAMES)
    parser.add_argument("--benchmark-snapshot", type=Path, help="Existing pinned input snapshot; no automatic fetch")
    args = parser.parse_args()
    result = run_suite(args.round_number, args.source_snapshot, tuple(args.task) if args.task else None, benchmark_snapshot=args.benchmark_snapshot)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
