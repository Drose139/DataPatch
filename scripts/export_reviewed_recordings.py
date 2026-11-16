"""Export completed operator-reviewed acceptance evidence, without execution.

    python scripts/export_reviewed_recordings.py results/acceptance/<report>.json

This exporter reads saved SQL, build and original pytest artifacts. It never
imports an Agent/provider, connects to a database, executes a verifier, or uses answers.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import difflib
import hashlib
import json
from pathlib import Path
import re
import uuid


ROOT = Path(__file__).resolve().parents[1]
REPORT_TYPE = "reviewed_patch_acceptance"


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object: {path}")
    return value


def _resolve(value: str | Path, root: Path, relative_to: Path) -> Path:
    text = str(value).replace("\\", "/")
    if text.startswith("$PROJECT/"):
        return root / text.removeprefix("$PROJECT/")
    path = Path(text)
    candidates = [path] if path.is_absolute() else [root / path, relative_to / path]
    for directory in ("external", "artifacts", "results", "examples"):
        marker = "/" + directory + "/"
        if marker in text:
            candidates.append(root / (directory + "/" + text.split(marker, 1)[1]))
    return next((item for item in candidates if item.exists()), candidates[0])


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _tests_passed(raw: dict) -> bool:
    executed = re.search(r"\b[1-9]\d* (?:passed|failed)\b[^\n]*\bin \d+(?:\.\d+)?s\b", raw.get("stdout", ""))
    if not executed or raw.get("returncode") != 0 or raw.get("reward") != 1:
        return False
    if raw.get("grading_protocol") == "pytest_exit_status":
        counts = raw.get("pytest_counts") or {}
        return (raw.get("pytest_returncode") == 0 and counts.get("passed", 0) > 0
                and all(counts.get(key) == 0 for key in ("failed", "errors", "skipped")))
    return bool(raw.get("components_passed")) and not raw.get("components_failed")


def audit_report(report: dict, report_path: Path, project_root: Path) -> dict:
    """Bind the saved acceptance to current bytes; hashing is not DB execution."""
    _require(report.get("status") == "completed", "Only completed acceptance reports can be exported")
    _require(report.get("type") == REPORT_TYPE and report.get("patch_origin") == "operator_reviewed",
             "Expected operator-reviewed patch acceptance, not an Agent evaluation")
    _require(report.get("zero_model_api_calls") is True, "Report must explicitly record zero model calls")
    policy = report.get("protocol", {}).get("acceptance_policy", "dbt_build")
    _require(policy in {"dbt_build", "upstream_harness"}, "Unsupported acceptance policy")
    build_required = policy == "dbt_build"
    if "acceptance_policy" in report.get("protocol", {}):
        _require(report["protocol"].get("build_required") is build_required, "Protocol build requirement conflicts with acceptance policy")
    rows = report.get("records", [])
    ids = [row.get("task_id") for row in rows]
    _require(len(rows) == report.get("planned_tasks") and len(set(ids)) == len(ids), "Incomplete or duplicate task records")
    _require(set(ids) == set(report.get("protocol", {}).get("task_ids", [])), "Task subset differs from the protocol")
    snapshot = report["input_snapshot"]
    lock_path = _resolve(snapshot["snapshot_lock"], project_root, report_path.parent)
    _require(_sha256(lock_path) == snapshot["snapshot_lock_sha256"], "Snapshot lock SHA-256 mismatch")
    lock = _read_json(lock_path)
    _require(lock.get("commit") == snapshot.get("commit"), "Snapshot commit mismatch")
    checked = {}
    for item in lock.get("files", []):
        path = lock_path.parent / item["path"]
        digest = _sha256(path)
        _require(digest == item["sha256"] and path.stat().st_size == item["bytes"], f"Input SHA-256 mismatch: {item['path']}")
        checked[item["path"]] = digest
    database = lock_path.parent / "base-image/database/retail.duckdb"
    database_hash = checked.get("base-image/database/retail.duckdb") or _sha256(database)
    _require(database_hash == snapshot["database_sha256"] == lock["database"]["sha256"]
             and database.stat().st_size == snapshot["database_bytes"] == lock["database"]["bytes"], "Original database byte hash mismatch")
    provenance = report.get("patch_provenance")
    if provenance:
        path = _resolve(provenance["path"], project_root, report_path.parent)
        _require(_sha256(path) == provenance["sha256"] and _read_json(path) == provenance["content"], "Patch provenance mismatch")
    # Public copies replace the originating workspace with $PROJECT. Compare
    # their JSON evidence after that same path-only redaction, not raw paths.
    normalized = lambda value: _clean(value, {str(project_root)})
    verified_rows = []
    for row in rows:
        task = row["task_id"]
        _require(row.get("patch_origin") == "operator_reviewed" and row.get("zero_api_calls") is True, f"Missing reviewed provenance: {task}")
        expected_inputs = [item for item in lock.get("files", []) if item["path"].startswith("tasks/" + task + "/")]
        _require(row.get("input_files") == expected_inputs, f"Recorded task inputs differ from snapshot: {task}")
        patch = _resolve(row["patch_source"], project_root, report_path.parent)
        case = _resolve(row["case_directory"], project_root, report_path.parent)
        _require(_sha256(patch) == row["patch_sha256"], f"Patch source SHA-256 mismatch: {task}")
        if not row.get("applied_patch_sha256"):
            errors = row.get("errors", [])
            _require(row.get("status") == "failed" and row.get("verification", {}).get("passed") is False
                     and errors and any(error.get("stage") == "prepare/apply" for error in errors),
                     f"Missing applied patch without explicit preparation failure: {task}")
            _require(all(error.get("stage") == "prepare/apply" or
                         (error.get("stage") == "evaluate" and error.get("type") == "FileNotFoundError") for error in errors),
                     f"Preparation-only failure contains later execution: {task}")
            _require(not row.get("raw_verifier") and not row.get("preparation")
                     and not (case / "native-case.json").exists(), f"Unexecuted failure contains case/verifier evidence: {task}")
            _require(not row.get("artifacts", {}).get("verifier_report"), f"Unexecuted failure contains a saved verifier report: {task}")
            for field in ("dependency_build", "build"):
                evidence = row.get(field, {})
                _require(evidence.get("success") is not True and evidence.get("target_model_success") is not True,
                         f"Unexecuted failure contains successful {field}: {task}")
                artifact_name = "dependency_build_report" if field == "dependency_build" else "build_report"
                if artifact_name in row.get("artifacts", {}):
                    saved = _resolve(row["artifacts"][artifact_name], project_root, report_path.parent)
                    _require(normalized(_read_json(saved)) == normalized(evidence), f"Saved unexecuted {field} differs: {task}")
            logs = [{"path": str(path), "sha256": _sha256(path)} for path in sorted((case / "preparation").glob("*.json"))]
            verified_rows.append({"task_id": task, "patch_sha256": row["patch_sha256"], "accepted": False,
                                  "unexecuted": True, "preparation_logs": logs})
            continue
        target = case / "project" / row["model_path"]
        _require(_sha256(patch) == row["patch_sha256"] == row.get("applied_patch_sha256") == _sha256(target), f"Applied patch SHA-256 mismatch: {task}")
        preparation = row["preparation"]
        _require(normalized(_read_json(case / "native-case.json")) == normalized(preparation) and preparation.get("task_id") == task
                 and preparation.get("upstream_commit") == snapshot["commit"], f"Fresh case metadata mismatch: {task}")
        build_path = _resolve(row["artifacts"]["build_report"], project_root, report_path.parent)
        verifier_path = _resolve(row["artifacts"]["verifier_report"], project_root, report_path.parent)
        raw = row["raw_verifier"]
        _require(normalized(_read_json(build_path)) == normalized(row["build"]), f"Saved build differs from report: {task}")
        dependency_path = None
        dependency_passed = True
        if not build_required:
            _require("dependency_build" in row, f"Upstream harness requires candidate materialization evidence: {task}")
        if "dependency_build" in row:
            dependency = row["dependency_build"]
            _require(isinstance(dependency, dict), f"Invalid dependency build evidence: {task}")
            _require(bool(row["artifacts"].get("dependency_build_report")), f"Missing saved dependency build: {task}")
            dependency_path = _resolve(row["artifacts"]["dependency_build_report"], project_root, report_path.parent)
            _require(normalized(_read_json(dependency_path)) == normalized(dependency), f"Saved dependency build differs from report: {task}")
            dependency_passed = dependency.get("success") is True and dependency.get("target_model_success") is True
            _require(row["verification"].get("dependency_build_success") is dependency_passed,
                     f"Dependency verdict conflicts with recorded run/target: {task}")
        if not build_required:
            _require(row["verification"].get("acceptance_policy") == policy
                     and row["verification"].get("build_required") is False
                     and row["verification"].get("target_materialization_success") is dependency_passed,
                     f"Materialization verdict conflicts with upstream acceptance policy: {task}")
            quality = row.get("project_quality", {})
            _require(normalized(quality.get("build")) == normalized(row["build"])
                     and quality.get("build_required") is False, f"Missing or altered project quality evidence: {task}")
        _require(normalized(_read_json(verifier_path)) == normalized(raw), f"Saved original verifier differs from report: {task}")
        _require(_sha256(verifier_path.parent / "test_outputs.original.py") == raw["original_sha256"], f"Original pytest SHA-256 mismatch: {task}")
        adapted_path = verifier_path.parent / ("test_outputs_" + re.sub(r"[^A-Za-z0-9_]", "_", case.name) + ".py")
        _require(_sha256(adapted_path) == raw["adapted_sha256"], f"Adapted pytest SHA-256 mismatch: {task}")
        if raw.get("scoring_source_sha256"):
            _require(_sha256(verifier_path.parent / "test.original.sh") == raw["scoring_source_sha256"], f"Original scoring script SHA-256 mismatch: {task}")
        required_errors = row.get("errors", [])
        passed = (not required_errors and dependency_passed
                  and (not build_required or (row["build"].get("success") is True
                       and row["build"].get("target_model_success") is True)) and _tests_passed(raw))
        _require(row["verification"].get("passed") is passed, f"Acceptance verdict conflicts with build/original tests: {task}")
        verified_rows.append({"task_id": task, "patch_sha256": row["patch_sha256"], "build_report_sha256": _sha256(build_path),
                              "verifier_report_sha256": _sha256(verifier_path), "accepted": passed})
        if dependency_path is not None:
            verified_rows[-1]["dependency_build_report_sha256"] = _sha256(dependency_path)
    accepted = sum(item["accepted"] for item in verified_rows)
    _require(report.get("summary", {}).get("accepted") == accepted, "Acceptance summary mismatch")
    return {"passed": True, "snapshot_lock_sha256": snapshot["snapshot_lock_sha256"],
            "input_files_checked": len(checked), "database_sha256": database_hash, "records": verified_rows}


def archived_run_id(report_name: str, task_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "datapatch:operator-reviewed:" + report_name + ":" + task_id))


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


def convert_record(row: dict, report: dict, report_path: Path, project_root: Path, audit: dict) -> dict:
    task_id, model_path = row["task_id"], row["model_path"]
    case = _resolve(row["case_directory"], project_root, report_path.parent)
    snapshot = _resolve(report["input_snapshot"]["snapshot_lock"], project_root, report_path.parent).parent
    original_instruction = snapshot / "tasks" / task_id / "instruction.md"
    instruction = original_instruction.read_text(encoding="utf-8-sig")
    heading = re.search(r"^#{1,6}\s+(.+)$", instruction, re.MULTILINE)
    title = heading.group(1).strip() if heading else task_id
    patch_path = _resolve(row["patch_source"], project_root, report_path.parent)
    integrity = next(item for item in audit["records"] if item["task_id"] == task_id)
    if integrity.get("unexecuted") is True:
        checks = [{"name": "prepare_success", "passed": False, "expected": True, "actual": False}]
        message = "准备阶段失败，补丁尚未应用，目标物化和上游原 pytest 未执行；该记录不计为验收通过。未调用模型。"
        output = {"run_id": archived_run_id(report["name"], task_id), "source_run_id": report["name"] + ":" + task_id,
                  "task_id": task_id, "task": {"id": task_id, "title": "公开项目 · 准备失败 · " + title,
                      "description": instruction, "split": "public-development"},
                  "provider": "operator_reviewed", "model": "未调用模型", "mode": "reviewed_patch",
                  "patch_origin": "operator_reviewed", "report_type": REPORT_TYPE, "status": "failed",
                  "archived": True, "recording_source": message, "execution_backend": "native_trusted",
                  "metrics": {"elapsed_seconds": row.get("elapsed_seconds", 0), "model_calls": 0, "tool_calls": 0,
                              "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0},
                  "recorded_operations": ["input preparation failed"], "zero_model_api_calls": True,
                  "events": [{"seq": 1, "type": "status", "content": message},
                             {"seq": 2, "type": "error", "content": row["errors"]},
                             {"seq": 3, "type": "final", "content": message}],
                  "diff": "", "checks": checks,
                  "verification": {**deepcopy(row["verification"]), "checks": checks, "unexecuted": True,
                                   "original_tests_executed": False, "target_materialization_executed": False},
                  "preparation_failure": {"errors": deepcopy(row["errors"]), "logs": deepcopy(integrity["preparation_logs"])},
                  "patch_sha256": row["patch_sha256"], "source_integrity": integrity,
                  "input_snapshot": deepcopy(report["input_snapshot"]), "input_files": deepcopy(row["input_files"]),
                  "public_benchmark": {"repository": report["input_snapshot"]["repository"], "commit": report["input_snapshot"]["commit"],
                                       "official_harbor_result": False, "setting": "native-adapted-public-development-case"},
                  "source_artifacts": {"report": str(report_path), "patch_source_not_applied": str(patch_path),
                                       "instruction": str(original_instruction), "preparation_logs": deepcopy(integrity["preparation_logs"])},
                  "error": "; ".join(item.get("error", str(item)) for item in row["errors"]), "final_answer": message}
        return _clean(output, {str(project_root)})
    after = patch_path.read_text(encoding="utf-8-sig")
    task_type = row["preparation"]["task_type"]
    if task_type == "create-model":
        before, original_path, fromfile = "", None, "/dev/null"
    elif task_type == "fix-model":
        if "bug_overlay" not in row["preparation"]:
            # Historical cases predate explicit overlay provenance.
            original_path = snapshot / "tasks" / task_id / "environment/data" / Path(model_path).name
        elif row["preparation"]["bug_overlay"] is None:
            original_path = snapshot / "base-image/dbt_models_duckdb" / model_path
        else:
            original_path = snapshot / "tasks" / task_id / row["preparation"]["bug_overlay"]
        before, fromfile = original_path.read_text(encoding="utf-8-sig"), "a/" + model_path
    else:
        raise ValueError(f"Unknown original task type: {task_type}")
    diff = "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=fromfile, tofile="b/" + model_path))
    build, raw = deepcopy(row["build"]), deepcopy(row["raw_verifier"])
    policy = report.get("protocol", {}).get("acceptance_policy", "dbt_build")
    quality_checks = [{"name": "final_build_success", "passed": build.get("success") is True, "expected": True, "actual": build.get("success")},
              {"name": "target_model_build_success", "passed": build.get("target_model_success") is True, "expected": True, "actual": build.get("target_model_success")}]
    checks = quality_checks if policy == "dbt_build" else []
    for field, passed in (("components_passed", True), ("components_failed", False)):
        checks.extend({"name": name, "passed": passed, "source": "saved original upstream pytest"} for name in raw.get(field, []))
    if raw.get("grading_protocol") == "pytest_exit_status":
        counts = raw["pytest_counts"]
        checks.append({"name": "pytest_executed_tests", "passed": counts["passed"] + counts["failed"] > 0,
                       "expected": ">0 (passed + failed)", "actual": counts["passed"] + counts["failed"]})
        for key, name in (("failed", "pytest_no_failures"), ("errors", "pytest_no_errors"), ("skipped", "pytest_no_skips")):
            checks.append({"name": name, "passed": counts[key] == 0, "expected": 0, "actual": counts[key]})
        checks.append({"name": "pytest_exit_status", "passed": raw.get("pytest_returncode") == 0, "expected": 0, "actual": raw.get("pytest_returncode")})
    passed = row["verification"]["passed"]
    source_id = report["name"] + ":" + task_id
    source = "已审阅补丁实际 dbt 构建与上游原 pytest 验收回放；operator_reviewed；未调用模型；该成品验收不属于自主 Agent 成绩。"
    output = {"run_id": archived_run_id(report["name"], task_id), "source_run_id": source_id,
              "task_id": task_id, "task": {"id": task_id, "title": "公开项目 · 已审阅成品 · " + title,
                  "description": instruction, "split": "public-development"},
              "provider": "operator_reviewed", "model": "未调用模型", "mode": "reviewed_patch",
              "patch_origin": "operator_reviewed", "report_type": REPORT_TYPE, "status": row["status"],
              "archived": True, "recording_source": source, "execution_backend": "native_trusted",
              "metrics": {"elapsed_seconds": row["elapsed_seconds"], "model_calls": 0, "tool_calls": 0,
                  "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0},
              "recorded_operations": ["dbt target build", "original upstream pytest"], "zero_model_api_calls": True,
              "events": [{"seq": 1, "type": "status", "content": source},
                  {"seq": 2, "type": "tool", "name": "已记录 dbt 构建", "arguments": {"select": Path(model_path).stem}, "result": build},
                  {"seq": 3, "type": "validation", "name": "已记录上游原 pytest", "result": raw},
                  {"seq": 4, "type": "final", "content": "成品补丁验收通过。" if passed else "成品补丁验收未通过。"}],
              "diff": diff, "applied_sql": after, "checks": checks,
              "verification": {**deepcopy(row["verification"]), "checks": checks},
              "final_build": build, "raw_verifier": raw, "preparation": deepcopy(row["preparation"]),
              "patch_sha256": row["patch_sha256"], "applied_patch_sha256": row["applied_patch_sha256"],
              "source_integrity": next(item for item in audit["records"] if item["task_id"] == task_id),
              "input_snapshot": deepcopy(report["input_snapshot"]), "input_files": deepcopy(row["input_files"]),
              "public_benchmark": {"repository": report["input_snapshot"]["repository"], "commit": report["input_snapshot"]["commit"],
                  "official_harbor_result": False, "setting": "native-adapted-public-development-case"},
              "source_artifacts": {"report": str(report_path), "patch": str(patch_path), "applied_sql": str(case / "project" / model_path),
                  "build_report": row["artifacts"]["build_report"], "verifier_report": row["artifacts"]["verifier_report"],
                  "instruction": str(original_instruction)},
              "final_answer": ("成品补丁已通过实际目标构建和上游原 pytest。" if passed else "成品补丁未通过独立验收。") + "未调用模型；自主 Agent 历史成绩另行保留。"}
    if original_path:
        output["source_artifacts"]["original_buggy_sql"] = str(original_path)
    if "dependency_build" in row:
        dependency = deepcopy(row["dependency_build"])
        dependency_passed = dependency.get("success") is True and dependency.get("target_model_success") is True
        dependency_checks = [
            {"name": "dependency_build_success", "passed": dependency_passed,
             "expected": True, "actual": dependency_passed},
            {"name": "dependency_target_model_success", "passed": dependency.get("target_model_success") is True,
             "expected": True, "actual": dependency.get("target_model_success")},
        ]
        output["checks"][:0] = dependency_checks
        output["final_dependency_build"] = dependency
        output["source_artifacts"]["dependency_build_report"] = row["artifacts"]["dependency_build_report"]
        output["recorded_operations"].insert(0, "dbt current candidate and ancestor run")
        output["events"].insert(1, {"type": "tool", "name": "已记录当前候选及祖先物化",
                                    "arguments": {"command": "run", "select": "+" + Path(model_path).stem}, "result": dependency})
        for seq, event in enumerate(output["events"], 1):
            event["seq"] = seq
    if "acceptance_policy" in report.get("protocol", {}):
        output["acceptance_policy"] = policy
    if policy == "upstream_harness":
        output["final_materialization"] = deepcopy(row["dependency_build"])
        materialized = row["verification"]["target_materialization_success"]
        output["checks"].insert(0, {"name": "target_materialization_success", "passed": materialized,
                                     "expected": True, "actual": materialized})
        output["project_quality"] = deepcopy(row["project_quality"])
        output["extra_quality"] = [{**check, "required": False} for check in quality_checks]
        notice = ("验收策略 upstream_harness：当前候选物化和上游原 pytest 是必需门槛。"
                  + ("附加 dbt build 已通过。" if build.get("success") is True else "附加 dbt build 未通过；完整失败结果保留在项目质量和执行轨迹中，不属于当前策略的验收门槛。"))
        output["recording_source"] += notice
        output["events"][0]["content"] += notice
        output["final_answer"] = ("成品补丁已通过当前候选物化和上游原 pytest。" if passed else "成品补丁未通过独立验收。") + notice + "未调用模型；自主 Agent 历史成绩另行保留。"
    if row.get("errors"):
        output["error"] = "; ".join(item.get("error", str(item)) for item in row["errors"])
    roots = {str(project_root)}
    text = str(report["input_snapshot"]["snapshot_lock"]).replace("\\", "/")
    if "/external/" in text and not text.startswith("$PROJECT/"):
        roots.add(text.split("/external/", 1)[0])
    return _clean(output, roots)


def export_report(report_path: Path, *, project_root: Path = ROOT, output_dir: Path | None = None) -> tuple[list[Path], dict]:
    project_root, report_path = project_root.resolve(), report_path.resolve()
    output_dir = (output_dir or project_root / "examples/recorded_runs").resolve()
    report = _read_json(report_path)
    audit = audit_report(report, report_path, project_root)
    converted = [convert_record(row, report, report_path, project_root, audit) for row in report["records"]]
    writes = []
    for record in converted:
        path = output_dir / (record["run_id"] + ".json")
        data = (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        _require(not path.exists() or path.read_bytes() == data, f"Existing archive differs; refusing overwrite: {path.name}")
        writes.append((path, data))
    output_dir.mkdir(parents=True, exist_ok=True)
    for path, data in writes:
        if not path.exists():
            path.write_bytes(data)
    return [path for path, _ in writes], audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    paths, audit = export_report(args.report, project_root=args.project_root, output_dir=args.output_dir)
    for path in paths:
        print(path)
    print(json.dumps({"exported": len(paths), "operator_reviewed": True, "model_calls": 0,
                      "source_integrity": audit}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
