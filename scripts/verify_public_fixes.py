"""Accept explicitly operator-reviewed SQL patches against original public tests.

No Agent or model provider is invoked. These results describe delivered patches,
not autonomous model performance. Benchmark HTTP downloads remain evaluator-only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from datapatch.config import ROOT
from datapatch.workspace import Workspace

_spec = importlib.util.spec_from_file_location("reviewed_patch_adapter", ROOT / "integrations/harbor_agent.py")
adapter = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(adapter)

REPORT_TYPE = "reviewed_patch_acceptance"
ACCEPTANCE_POLICIES = ("dbt_build", "upstream_harness")
DEFAULT_TASKS = ("dbt-fix-product-metrics", "dbt-fix-refund-reconciliation", "dbt-fix-division-by-zero", "dbt-fix-inventory-model")
CASE_NAMES = dict(zip(DEFAULT_TASKS, ("product", "refund", "division", "inventory")))
CASE_NAMES.update({"dbt-fix-timezone-sales": "timezone", "dbt-fix-daily-revenue": "daily",
                   "dbt-exchange-rate-settlement-date": "fx", "cohort-retention-matrix": "cohort"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _original_tests_passed(raw: dict) -> bool:
    executed = bool(re.search(r"\b[1-9]\d* (?:passed|failed)\b[^\n]*\bin \d+(?:\.\d+)?s\b", raw.get("stdout", "")))
    if not executed or raw.get("returncode") != 0 or raw.get("reward") != 1:
        return False
    if raw.get("grading_protocol") == "pytest_exit_status":
        counts = raw.get("pytest_counts") or {}
        return (raw.get("pytest_returncode") == 0 and counts.get("passed", 0) > 0
                and all(counts.get(key) == 0 for key in ("failed", "errors", "skipped")))
    return bool(raw.get("components_passed")) and not raw.get("components_failed")


def _save_report(report: dict, output: Path) -> None:
    accepted = sum(row["verification"]["passed"] is True for row in report["records"])
    report["summary"] = {"task_count": report["planned_tasks"], "accepted": accepted,
                         "not_accepted": report["planned_tasks"] - accepted,
                         "acceptance_rate": accepted / report["planned_tasks"]}
    report["status"] = "completed" if len(report["records"]) == report["planned_tasks"] else "running"
    _write_json(output, report)
    lines = ["# 公开任务成品补丁验收", "", "类型：`reviewed_patch_acceptance`；补丁来源：`operator_reviewed`。",
             "", "本报告不属于自主 Agent 试验，未调用模型 API，不产生模型调用数或 token 指标。历史自主执行成绩保持原样。",
             "", f"已接受 {accepted}/{report['planned_tasks']} 个预登记任务。", "",
             "验收策略：`" + report["protocol"]["acceptance_policy"] + "`。额外 dbt build 原始结果始终保留；upstream_harness 以真实目标物化和原 pytest 为门槛。", "",
             "| 任务 | 依赖 run | 目标 build | 原 pytest reward | 补丁验收 |", "|---|---|---|---:|---|"]
    for row in report["records"]:
        lines.append(f"| {row['task_id']} | {row['dependency_build'].get('success', False)} | {row['build'].get('success', False)} | {row.get('raw_verifier', {}).get('reward', 'unavailable')} | {row['verification']['passed']} |")
    for row in report["records"]:
        lines += ["", "## " + row["task_id"], "", "Patch SHA-256：`" + row["patch_sha256"] + "`。",
                  "", "当前候选及祖先 run stdout：", "", "```text", row["dependency_build"].get("stdout", ""), "```",
                  "", "原 build stdout：", "", "```text", row["build"].get("stdout", ""), "```",
                  "", "原 pytest stdout：", "", "```text", row.get("raw_verifier", {}).get("stdout", ""), "```"]
    output.with_suffix(".md").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def verify_fixes(patch_root: Path, case_root: Path, output: Path, tasks: tuple[str, ...] | None = None, *, snapshot: Path | None = None, acceptance_policy: str = "dbt_build", duckdb_timezone: str | None = None, packages_cache: Path | None = None) -> dict:
    if duckdb_timezone not in (None, "UTC"):
        raise ValueError("Explicit DuckDB timezone must be UTC or omitted")
    if acceptance_policy not in ACCEPTANCE_POLICIES:
        raise ValueError("Unsupported acceptance policy")
    build_required = acceptance_policy == "dbt_build"
    selected = DEFAULT_TASKS if tasks is None else tuple(tasks)
    if not selected or len(selected) != len(set(selected)) or any(task not in adapter.PUBLIC_TASK_MODELS for task in selected):
        raise ValueError("Choose a nonempty unique subset of the fixed public tasks")
    patch_root, case_root, output = patch_root.resolve(), case_root.resolve(), output.resolve()
    snapshot = (snapshot or ROOT / "external/data-eng-bench").resolve()
    archive_root = output.parent / (output.stem + "_artifacts")
    if case_root.exists() or output.exists() or output.with_suffix(".md").exists() or archive_root.exists():
        raise ValueError("Case root, acceptance report, and archive must be new; historical results cannot be overwritten")
    if archive_root == case_root or case_root in archive_root.parents or archive_root in case_root.parents:
        raise ValueError("Acceptance artifacts must be outside the isolated case root")
    patches = {}
    for task in selected:
        path = patch_root / (task + ".sql")
        data = path.read_bytes()
        if not re.search(r"(?im)^\s*--\s*operator_reviewed\b", data.decode("utf-8-sig")):
            raise ValueError(f"Patch must explicitly contain -- operator_reviewed: {path.name}")
        patches[task] = {"path": path, "data": data, "sha256": hashlib.sha256(data).hexdigest()}
    lock_path = snapshot / "snapshot-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("commit") != adapter.PINNED_COMMIT or not set(selected) <= set(lock.get("tasks", [])):
        raise ValueError("Input snapshot commit/task subset does not match the pinned benchmark")
    database = snapshot / "base-image/database/retail.duckdb"
    database_hash = _sha256(database)
    if database_hash != lock["database"]["sha256"] or database.stat().st_size != lock["database"]["bytes"]:
        raise ValueError("Original input database does not match the pinned snapshot hash")
    report = {"type": REPORT_TYPE, "report_type": REPORT_TYPE, "name": output.stem,
              "created_at": datetime.now(timezone.utc).isoformat(), "patch_origin": "operator_reviewed",
              "zero_api_calls": True, "zero_model_api_calls": True,
              "api_call_definition": "Model generation requests; benchmark/verifier file downloads are not model API calls",
              "planned_tasks": len(selected), "protocol": {"task_ids": list(selected), "patch_origin": "operator_reviewed",
                  "acceptance_policy": acceptance_policy, "build_required": build_required,
                  "dependency_materialization": "run +target after applying candidate, then build target only",
                  "automatic_retries": False, "verifier_feedback_to_agent": False},
              "input_snapshot": {"repository": lock.get("repository"), "commit": lock["commit"],
                  "snapshot_lock": str(lock_path), "snapshot_lock_sha256": _sha256(lock_path),
                  "database_sha256": database_hash, "database_bytes": database.stat().st_size},
              "records": [], "limitations": ["Operator-reviewed SQL acceptance is distinct from autonomous Agent results.",
                  "Fixed public development subset under Windows native path adaptation; not an official Harbor score."]}
    if duckdb_timezone is not None:
        report["protocol"]["runtime_settings"] = {"duckdb_timezone": duckdb_timezone}
        report["limitations"].append("Explicit UTC DuckDB sessions apply to dbt and the original pytest verifier; assertions, SQL logic, and source data are unchanged.")
    if packages_cache is not None:
        packages_cache = packages_cache.resolve()
        report["protocol"]["packages_cache"] = str(packages_cache)
        report["protocol"]["packages_cache_receipt_sha256"] = _sha256(packages_cache / "receipt.json")
        report["limitations"].append("A verified byte-identical pinned dbt_utils package is resolved through a local runtime path; original package declarations and lock bytes are archived.")
    provenance = patch_root / "provenance.json"
    expanded_provenance = patch_root / "expanded-provenance.json"
    if expanded_provenance.is_file():
        expanded = json.loads(expanded_provenance.read_text(encoding="utf-8"))
        if set(selected) <= set(expanded):
            provenance = expanded_provenance
    if provenance.is_file():
        report["patch_provenance"] = {"path": str(provenance), "sha256": _sha256(provenance),
                                      "content": json.loads(provenance.read_text(encoding="utf-8"))}
    case_root.mkdir(parents=True, exist_ok=False)
    archive_root.mkdir(parents=True, exist_ok=False)
    # Freeze the selected cases and acceptance policy before the first build.
    _save_report(report, output)
    for task in selected:
        patch = patches[task]
        case = case_root / CASE_NAMES[task]
        model_path = adapter.PUBLIC_TASK_MODELS[task]
        item_archive = archive_root / task
        item_archive.mkdir()
        row = {"task_id": task, "patch_origin": "operator_reviewed", "zero_api_calls": True,
               "patch_source": str(patch["path"]), "patch_sha256": patch["sha256"],
               "model_path": model_path, "case_directory": str(case), "status": "failed",
               "dependency_build": {"success": False}, "build": {"success": False}, "verification": {"passed": False}, "errors": [],
               "input_files": [item for item in lock.get("files", []) if item.get("path", "").startswith("tasks/" + task + "/")]}
        began = time.monotonic()
        prepared = False
        print(f"REVIEWED PATCH {task}: prepare original inputs", flush=True)
        try:
            prepare_options = {"duckdb_timezone": duckdb_timezone} if duckdb_timezone is not None else {}
            if packages_cache is not None:
                prepare_options["packages_cache"] = packages_cache
            row["preparation"] = adapter.prepare_native_case(snapshot, case, task, **prepare_options)
            prepared_timezone = row["preparation"].get("runtime_settings", {}).get("duckdb_timezone")
            workspace_options = {"duckdb_timezone": prepared_timezone} if prepared_timezone is not None else {}
            target = (case / "project" / model_path).resolve()
            if not target.is_relative_to((case / "project/models").resolve()):
                raise ValueError("Patch target must remain under the isolated models directory")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(patch["data"])
            row["applied_patch_sha256"] = _sha256(target)
            if row["applied_patch_sha256"] != patch["sha256"]:
                raise ValueError("Applied SQL bytes differ from the reviewed patch")
            prepared = True
        except Exception as exc:
            row["errors"].append({"stage": "prepare/apply", "type": type(exc).__name__, "error": str(exc)})
        if prepared:
            print(f"REVIEWED PATCH {task}: materialize candidate and current ancestors", flush=True)
            try:
                workspace = Workspace(case, project_dir=case / "project", database_path=case / "database/retail.duckdb", **workspace_options)
                dependency_result = workspace.run_dbt("run", select="+" + Path(model_path).stem)
                row["dependency_build"] = adapter.verify_target_build(dependency_result, case / "project", model_path)
            except Exception as exc:
                row["errors"].append({"stage": "dependency_build", "type": type(exc).__name__, "error": str(exc)})
            print(f"REVIEWED PATCH {task}: build target", flush=True)
            try:
                workspace = Workspace(case, project_dir=case / "project", database_path=case / "database/retail.duckdb", **workspace_options)
                result = workspace.run_dbt("build", select=Path(model_path).stem)
                row["build"] = adapter.verify_target_build(result, case / "project", model_path)
            except Exception as exc:
                row["errors"].append({"stage": "build", "type": type(exc).__name__, "error": str(exc)})
        build_archive = item_archive / "build.json"
        dependency_archive = item_archive / "dependency_build.json"
        _write_json(dependency_archive, row["dependency_build"])
        _write_json(build_archive, row["build"])
        row["project_quality"] = {"build": row["build"], "build_required": build_required,
                                  "role": "required acceptance gate" if build_required else "additional project dbt checks; not the upstream harness gate"}
        row["artifacts"] = {"build_report": str(build_archive), "dependency_build_report": str(dependency_archive),
                            "verifier_directory": str(archive_root / "verifiers" / task)}
        print(f"REVIEWED PATCH {task}: original independent pytest", flush=True)
        try:
            result = adapter.evaluate_native_case(case, archive_root / "verifiers")
            verifier_path = Path(result["report"])
            raw = json.loads(verifier_path.read_text(encoding="utf-8"))
            row["raw_verifier"] = raw
            row["artifacts"]["verifier_report"] = str(verifier_path)
            materialized = (row["dependency_build"].get("success") is True
                            and row["dependency_build"].get("target_model_success") is True)
            build_passed = row["build"].get("success") is True and row["build"].get("target_model_success") is True
            # A returned dbt test failure is optional quality under upstream_harness.
            # Python/IO/artifact exceptions are execution failures under every policy.
            required_errors = row["errors"]
            row["verification"] = {"passed": not required_errors and materialized and (build_passed or not build_required) and _original_tests_passed(raw),
                                   "acceptance_policy": acceptance_policy, "build_required": build_required,
                                   "target_materialization_success": materialized,
                                   "dependency_build_success": materialized,
                                   "original_tests_passed": _original_tests_passed(raw), "reward": raw.get("reward"),
                                   "grading_protocol": raw.get("grading_protocol", "component_reward_json")}
            row["status"] = "completed" if not required_errors else "failed"
        except Exception as exc:
            row["errors"].append({"stage": "evaluate", "type": type(exc).__name__, "error": str(exc)})
        row["elapsed_seconds"] = round(time.monotonic() - began, 3)
        report["records"].append(row)
        _save_report(report, output)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch-root", type=Path, default=ROOT / "examples/public_fixes")
    parser.add_argument("--case-root", type=Path, default=ROOT / "external/native-cases/public-fixes-20261026")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/acceptance/public_fixes_20261026.json")
    parser.add_argument("--snapshot", type=Path, default=ROOT / "external/data-eng-bench")
    parser.add_argument("--task", action="append", choices=adapter.PUBLIC_TASK_MODELS)
    parser.add_argument("--acceptance-policy", choices=ACCEPTANCE_POLICIES, default="dbt_build")
    parser.add_argument("--duckdb-timezone", choices=("UTC",), help="Explicit UTC sessions for dbt and unchanged original pytest; omitted keeps native defaults")
    parser.add_argument("--packages-cache", type=Path, help="Verified pinned dbt_utils cache for offline local dependency resolution")
    args = parser.parse_args()
    report = verify_fixes(args.patch_root, args.case_root, args.output, tuple(args.task) if args.task else None,
                          snapshot=args.snapshot, acceptance_policy=args.acceptance_policy, duckdb_timezone=args.duckdb_timezone, packages_cache=args.packages_cache)
    print(json.dumps({"type": REPORT_TYPE, "zero_api_calls": True, "summary": report["summary"], "report": str(args.output.resolve())}, ensure_ascii=True))
    return 0 if report["summary"]["accepted"] == report["planned_tasks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
