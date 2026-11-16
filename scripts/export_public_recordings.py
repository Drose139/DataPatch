"""Archive completed native public runs for replay, without executing any tools.

Usage:
    python scripts/export_public_recordings.py artifacts/evaluations/<report>.json
    python scripts/export_public_recordings.py <report>.json --run-id <source_run_id>

Inputs are the saved evaluation, agent JSON/JSONL/patch, original verifier JSON,
and optional public instruction.md. No database, reference answer, or API is used.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import uuid


ROOT = Path(__file__).resolve().parents[1]


def archived_run_id(source_run_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "datapatch:public-native:" + source_run_id))


def resolve_artifact(value: str | Path, project_root: Path, relative_to: Path) -> Path:
    text = str(value).replace("\\", "/")
    if text.startswith("$PROJECT/"):
        return project_root / text[len("$PROJECT/"):]
    path = Path(text)
    candidates = [path] if path.is_absolute() else [project_root / path, relative_to / path]
    # A shipped report can retain an absolute path from the originating machine.
    for directory in ("external", "artifacts", "results"):
        marker = "/" + directory + "/"
        if marker in text:
            candidates.append(project_root / (directory + "/" + text.split(marker, 1)[1]))
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return data


def _clean(value, roots: set[str]):
    if isinstance(value, str):
        for root in sorted(roots, key=len, reverse=True):
            for spelling in (root.replace("\\", "/"), root.replace("/", "\\")):
                value = re.sub(re.escape(spelling), lambda _: "$PROJECT", value, flags=re.IGNORECASE)
        return value
    if isinstance(value, dict):
        return {key: _clean(item, roots) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item, roots) for item in value]
    return value


def _instruction(record: dict, agent: dict, agent_path: Path, project_root: Path) -> tuple[str | None, Path | None]:
    candidates = []
    for metadata in (record, agent):
        if metadata.get("instruction_path"):
            candidates.append(resolve_artifact(metadata["instruction_path"], project_root, agent_path.parent))
        if metadata.get("case_dir"):
            candidates.append(resolve_artifact(str(metadata["case_dir"]) + "/instruction.md", project_root, agent_path.parent))
    mode = record.get("mode", agent.get("mode", "verified"))
    suffix = "-" + mode
    case_name = agent_path.stem.removesuffix(suffix)
    candidates.extend([
        agent_path.parent.parent / "native-cases" / case_name / "instruction.md",
        project_root / "external/native-cases" / case_name / "instruction.md",
    ])
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    return (path.read_text(encoding="utf-8-sig"), path) if path else (None, None)


def convert_record(record: dict, report: dict, report_path: Path, project_root: Path) -> dict:
    source_id = record.get("run_id")
    if not isinstance(source_id, str) or not source_id:
        raise ValueError("Every source record must have a run_id")
    if not isinstance(record.get("verification", {}).get("passed"), bool):
        raise ValueError(f"Source verdict is not a boolean: {source_id}")
    agent_path = resolve_artifact(record["agent_report"], project_root, report_path.parent)
    verifier_path = resolve_artifact(record["verifier_report"], project_root, report_path.parent)
    agent = _read_json(agent_path)
    verifier = _read_json(verifier_path)
    agent_result = agent.get("result", {})
    events_path = agent_path.with_suffix(".jsonl")
    patch_path = agent_path.with_suffix(".patch")
    events = []
    for line in events_path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError(f"Expected a JSONL event object: {events_path}")
        # Preserve real timestamps when present; never assign export times.
        events.append({**event, "seq": len(events) + 1})
    patch = patch_path.read_text(encoding="utf-8-sig")
    instruction, instruction_path = _instruction(record, agent, agent_path, project_root)
    task_id = record.get("task_id", agent.get("task_id"))
    if not task_id:
        raise ValueError(f"Missing task_id: {source_id}")
    original_task = record.get("task") or {}
    title = original_task.get("title") or task_id
    if instruction and not original_task.get("title"):
        heading = re.search(r"^#{1,6}\s+(.+)$", instruction, re.MULTILINE)
        if heading:
            title = heading.group(1).strip()
    description = original_task.get("description") or record.get("description") or instruction
    if not description:
        description = "data-eng-bench 公开开发任务；该记录未附原始工单正文，请查看来源报告。"
    verification = deepcopy(record["verification"])
    checks = deepcopy(verification.get("checks", []))
    final_build = deepcopy(record.get("final_build", agent.get("final_build")))
    if isinstance(final_build, dict):
        build_check = {"name": "final_build_success", "passed": final_build.get("success"),
                       "expected": True, "actual": final_build.get("success"), "source": "saved final_build"}
        if "evidence" in final_build:
            build_check["evidence"] = final_build["evidence"]
        checks.append(build_check)
    for field, passed in (("components_passed", True), ("components_failed", False)):
        for component in verifier.get(field, []):
            checks.append({"name": component, "passed": passed, "source": "original upstream verifier"})
    if verifier.get("grading_protocol") == "pytest_exit_status":
        counts = verifier.get("pytest_counts") or {}
        passed_count, failed_count = counts.get("passed"), counts.get("failed")
        valid_count = lambda value: isinstance(value, int) and not isinstance(value, bool) and value >= 0
        executed = passed_count + failed_count if valid_count(passed_count) and valid_count(failed_count) else None
        checks.append({"name": "pytest_executed_tests", "passed": executed > 0 if executed is not None else None,
                       "expected": ">0 (passed + failed)", "actual": executed,
                       "source": "saved pytest_counts; preserves original overall verdict"})
        for key, name in (("failed", "pytest_no_failures"), ("errors", "pytest_no_errors"), ("skipped", "pytest_no_skips")):
            count = counts.get(key)
            checks.append({"name": name, "passed": count == 0 if valid_count(count) else None,
                           "expected": 0, "actual": count,
                           "source": "saved pytest_counts; preserves original overall verdict"})
        exit_status = verifier.get("pytest_returncode")
        checks.append({"name": "pytest_exit_status", "passed": exit_status == 0 if isinstance(exit_status, int) else None,
                       "expected": 0, "actual": exit_status, "source": "saved pytest_returncode"})
    verification["checks"] = checks
    output = {
        "run_id": archived_run_id(source_id), "source_run_id": source_id,
        "task_id": task_id,
        "task": {**deepcopy(original_task), "id": task_id, "title": "公开项目 · " + title,
                 "description": description, "split": "public-development"},
        "mode": record.get("mode", agent.get("mode", "verified")),
        "provider": "deepseek", "model": record.get("model", agent.get("model")),
        "status": record["status"], "events": events,
        "metrics": deepcopy(record.get("metrics", agent_result.get("metrics", {}))),
        "diff": patch, "checks": checks, "verification": verification,
        "raw_verifier": verifier, "archived": True, "execution_backend": "native_trusted",
        "recording_source": "已记录真实公开运行回放；来自实际 DeepSeek API、原始工具事件、补丁与上游验收，导出未重新执行模型或验收。",
        "source_artifacts": {"report": str(report_path), "agent_report": str(agent_path),
                             "events": str(events_path), "patch": str(patch_path),
                             "verifier_report": str(verifier_path)},
        "public_benchmark": {"repository": report.get("upstream_repository"),
                             "commit": report.get("upstream_commit", agent.get("commit")),
                             "official_harbor_result": False,
                             "setting": agent.get("setting", "native-adapted-public-development-case")},
    }
    if final_build is not None:
        output["final_build"] = final_build
    if instruction_path:
        output["source_artifacts"]["instruction"] = str(instruction_path)
    for key in ("started_at", "finished_at", "max_steps", "budget_usd", "generation_settings", "model_config",
                "observed_model_versions", "source_sha256", "source_snapshot", "source_snapshot_sha256",
                "agent_revision", "stop_reason", "final_answer", "candidate_review", "visible_validation", "error",
                "execution_error", "error_type", "failure_category", "public_contracts", "target_start", "assistance"):
        for source in (record, agent_result, agent):
            if key in source:
                output[key] = deepcopy(source[key])
                break
    execution_error = output.get("execution_error") or output.get("error")
    failure_category = output.get("failure_category")
    if execution_error or failure_category:
        parts = [str(value) for value in (failure_category, execution_error) if value]
        output["error"] = ": ".join(dict.fromkeys(parts))
    roots = {str(project_root)}
    for value in (record.get("agent_report"), record.get("verifier_report"), record.get("source_snapshot"), agent.get("events")):
        text = str(value or "").replace("\\", "/")
        for marker in ("/external/", "/artifacts/", "/results/"):
            if marker in text:
                prefix = text.split(marker, 1)[0]
                if prefix and prefix != "$PROJECT":
                    roots.add(prefix)
    return _clean(output, roots)


def export_reports(report_paths: list[Path], *, project_root: Path = ROOT,
                   output_dir: Path | None = None, run_ids: set[str] | None = None) -> list[Path]:
    project_root = project_root.resolve()
    output_dir = (output_dir or project_root / "examples/recorded_runs").resolve()
    converted = {}
    found = set()
    for report_path in report_paths:
        report_path = report_path.resolve()
        report = _read_json(report_path)
        if report.get("status") != "completed":
            raise ValueError(f"Only completed reports can be archived: {report_path.name}")
        for record in report.get("records", []):
            if run_ids is not None and record.get("run_id") not in run_ids:
                continue
            result = convert_record(record, report, report_path, project_root)
            if result["run_id"] in converted:
                raise ValueError(f"Duplicate source run_id: {record['run_id']}")
            converted[result["run_id"]] = result
            found.add(record["run_id"])
    if run_ids is not None and run_ids - found:
        raise ValueError("Requested source runs not found: " + ", ".join(sorted(run_ids - found)))
    if not converted:
        raise ValueError("No recorded runs selected")
    # Resolve every input first so a missing source never leaves a partial export.
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for run_id, record in converted.items():
        path = output_dir / (run_id + ".json")
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+", help="Completed public evaluation JSON reports")
    parser.add_argument("--run-id", action="append", dest="run_ids", help="Select original run_id; repeat to select several")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, help="Default: <project-root>/examples/recorded_runs")
    args = parser.parse_args(argv)
    paths = export_reports(args.reports, project_root=args.project_root, output_dir=args.output_dir,
                           run_ids=set(args.run_ids) if args.run_ids else None)
    for path in paths:
        print(path)
    print(f"Exported {len(paths)} actual public recordings. No model, database or verifier was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
