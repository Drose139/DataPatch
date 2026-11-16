"""Offline consistency checks for recorded DataPatch evaluations.

This module never invokes a model, executes archived code, or changes reports.
An audit passing means the checked records are internally consistent. It does
not certify the evaluator's business logic or the underlying model's quality.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


class _Checks:
    def __init__(self) -> None:
        self.errors: list[dict] = []
        self.warnings: list[dict] = []
        self.checks: list[dict] = []

    def add(self, status: str, code: str, message: str, **details: Any) -> None:
        item = {"code": code, "message": message, **details}
        self.checks.append({"status": status, **item})
        if status == "failed":
            self.errors.append(item)
        elif status == "warning":
            self.warnings.append(item)

    def test(self, condition: bool, code: str, message: str, **details: Any) -> None:
        self.add("passed" if condition else "failed", code, message, **details)

    def result(self) -> dict:
        return {"passed": not self.errors, "errors": self.errors, "warnings": self.warnings, "checks": self.checks}


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _differences(expected: Any, actual: Any, path: str = "summary") -> list[str]:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected object, found {type(actual).__name__}"]
        return [difference for key, value in expected.items() for difference in _differences(value, actual.get(key), f"{path}.{key}")]
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return [f"{path}: list length/type differs"]
        return [difference for i, value in enumerate(expected) for difference in _differences(value, actual[i], f"{path}[{i}]")]
    if isinstance(expected, bool) or isinstance(actual, bool):
        equal = expected is actual
    elif _numeric(expected) and _numeric(actual):
        equal = math.isclose(expected, actual, rel_tol=1e-9, abs_tol=1e-9)
    else:
        equal = expected == actual
    return [] if equal else [f"{path}: expected {expected!r}, found {actual!r}"]


def _check_matrix(report: dict, records: list[dict], audit: _Checks) -> None:
    planned = report.get("planned_trials")
    audit.test(_integer(planned) and planned >= 0, "planned_trials_type", "planned_trials must be a nonnegative integer")
    if _integer(planned):
        audit.test(planned == len(records), "trial_count", "Recorded trials must equal planned_trials", planned=planned, recorded=len(records))
    run_ids = [row.get("run_id") for row in records]
    audit.test(all(isinstance(value, str) and value for value in run_ids), "run_ids_present", "Every trial needs a nonempty run_id")
    duplicates = [value for value, count in Counter(str(x) for x in run_ids if x is not None).items() if count > 1]
    audit.test(not duplicates, "duplicate_run_id", "Trial run_ids must be unique", duplicates=duplicates)
    protocol = report.get("protocol") or {}
    tasks = protocol.get("planned_task_ids", protocol.get("task_ids"))
    modes, repeats = protocol.get("modes"), protocol.get("repeats")
    if not isinstance(tasks, list) or not isinstance(modes, list) or not _integer(repeats) or repeats < 1:
        audit.add("warning", "protocol_matrix_unverifiable", "Task × mode × repeat protocol is incomplete; matrix coverage was not verified")
        return
    if not all(isinstance(value, str) and value for value in tasks + modes):
        audit.add("failed", "protocol_dimensions", "Protocol task_ids and modes must contain nonempty strings")
        return
    audit.test(len(tasks) == len(set(tasks)) and len(modes) == len(set(modes)), "protocol_dimensions_unique", "Protocol task_ids and modes must not repeat")
    expected = set(itertools.product(tasks, modes, range(repeats)))
    if _integer(planned):
        audit.test(planned == len(expected), "protocol_planned_trials", "planned_trials must match task × mode × repeats", matrix_trials=len(expected), planned=planned)
    actual: list[tuple] = []
    for i, row in enumerate(records):
        repeat = row.get("repeat")
        if repeat is None and repeats == 1:
            repeat = 0
            audit.add("warning", "single_repeat_inferred", "Missing repeat inferred as 0 for a one-trial protocol", record=i)
        if not _integer(repeat):
            audit.add("failed", "repeat_type", "Trial repeat must be an integer", record=i)
            continue
        actual.append((str(row.get("task_id")), str(row.get("mode")), repeat))
    counts = Counter(actual)
    missing = sorted(expected - set(actual))
    extra = sorted(set(actual) - expected)
    repeated = sorted(key for key, count in counts.items() if count > 1)
    audit.test(not missing, "missing_trials", "Every protocol combination must be present", missing=missing)
    audit.test(not extra, "unexpected_trials", "Trials must belong to the frozen protocol", unexpected=extra)
    audit.test(not repeated, "duplicate_trial", "A protocol combination must occur once", duplicates=repeated)


def _check_records(records: list[dict], audit: _Checks) -> None:
    for i, row in enumerate(records):
        identity = row.get("run_id", str(i))
        verification = row.get("verification") or {}
        flag = verification.get("passed", False)
        audit.test(isinstance(flag, bool), "verification_flag_type", "verification.passed must be a boolean", run_id=identity)
        if flag is True:
            audit.test(row.get("status") == "completed", "passed_incomplete_execution", "A passing trial must have completed execution", run_id=identity, execution_status=str(row.get("status")))
            audit.test((row.get("final_build") or {}).get("success") is True, "passed_failed_build", "A passing trial requires a recorded successful final build", run_id=identity)
        metrics = row.get("metrics") or {}
        if not isinstance(metrics, dict):
            audit.add("failed", "metrics_type", "Trial metrics must be an object", run_id=identity)
            continue
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "model_calls", "tool_calls"):
            if key in metrics:
                value = metrics[key]
                audit.test(_integer(value) and value >= 0, "nonnegative_counter", f"{key} must be a nonnegative integer", run_id=identity)
        for key in ("estimated_cost_usd", "elapsed_seconds"):
            if key in metrics:
                audit.test(_numeric(metrics[key]) and metrics[key] >= 0, "nonnegative_measure", f"{key} must be finite and nonnegative", run_id=identity)
        usage = [metrics.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")]
        if all(_integer(value) for value in usage):
            audit.test(usage[0] + usage[1] == usage[2], "token_sum", "total_tokens must equal prompt_tokens + completion_tokens", run_id=identity)
        else:
            audit.add("warning", "token_usage_unverifiable", "Complete token usage is unavailable; token addition was not verified", run_id=identity)


def _check_public_verifiers(report: dict, records: list[dict], audit: _Checks) -> None:
    public_report = "data-eng-bench" in str(report.get("dataset", ""))
    for i, row in enumerate(records):
        raw = row.get("raw_verifier")
        identity = row.get("run_id", str(i))
        if raw is None:
            if public_report:
                audit.add("warning", "public_verifier_unavailable", "Public trial has no raw verifier evidence; reward and test execution were not verified", run_id=identity)
            continue
        if not isinstance(raw, dict):
            audit.add("failed", "public_verifier_schema", "raw_verifier must be an object", run_id=identity)
            continue
        if raw.get("mode") != "native-path-adapted-upstream-verifier":
            audit.add("warning", "public_verifier_schema_unknown", "Unknown raw verifier format; public reward consistency was not verified", run_id=identity)
            continue
        verification = row.get("verification") or {}
        reward, returncode = raw.get("reward"), raw.get("returncode")
        if raw.get("grading_protocol") == "pytest_exit_status":
            counts = raw.get("pytest_counts") or {}
            valid_counts = all(_integer(counts.get(key)) and counts[key] >= 0 for key in ("passed", "failed", "errors", "skipped"))
            valid_scalars = _numeric(reward) and reward in (0, 1) and _integer(returncode)
            audit.test(valid_counts and valid_scalars, "public_pytest_count_schema", "Plain pytest grading requires actual counts, exit status and binary reward", run_id=identity)
            if not valid_counts or not valid_scalars:
                continue
            stdout = raw.get("stdout") or ""
            summaries = [line for line in stdout.splitlines() if re.search(r"\bin \d+(?:\.\d+)?s\b", line) and re.search(r"\d+ (?:passed|failed|errors?|skipped)", line)]
            final_summary = summaries[-1] if summaries else ""
            parsed = {key: 0 for key in counts}
            for number, label in re.findall(r"\b(\d+) (passed|failed|errors?|skipped)\b", final_summary):
                parsed["errors" if label in {"error", "errors"} else label] = int(number)
            actual_execution = bool(final_summary) and counts["passed"] + counts["failed"] > 0
            audit.test(actual_execution and parsed == counts, "public_pytest_counts_match_stdout", "Plain pytest counts must agree with the actual final summary", run_id=identity)
            raw_pass = actual_execution and returncode == 0 and counts["passed"] > 0 and not any(counts[key] for key in ("failed", "errors", "skipped"))
            audit.test(reward == (1.0 if raw_pass else 0.0), "public_reward_matches_pytest", "Reward must follow the pinned test.sh pytest scoring rule", run_id=identity)
            expected_pass = raw_pass and row.get("status") == "completed" and bool((row.get("final_build") or {}).get("success"))
            audit.test(verification.get("passed") is expected_pass, "public_pass_matches_raw_verifier", "Final delivery requires completed execution, build and raw pytest success", run_id=identity)
            audit.test(verification.get("reward") == reward, "public_verification_matches_raw", "Saved reward must match raw pytest grading", run_id=identity)
            source_hash = raw.get("scoring_source_sha256")
            audit.test(isinstance(source_hash, str) and bool(re.fullmatch(r"[a-f0-9]{64}", source_hash)), "public_scoring_source_hash", "Adapted pytest scoring must identify the original pinned scoring script", run_id=identity)
            if "valid_pytest_execution" in verification:
                audit.test(verification["valid_pytest_execution"] is actual_execution, "public_execution_flag_matches_evidence", "Execution flag must agree with actual pytest summary", run_id=identity)
            continue
        passed, failed = raw.get("components_passed"), raw.get("components_failed")
        valid_lists = all(isinstance(values, list) and all(isinstance(value, str) and value for value in values) for values in (passed, failed))
        valid_scalars = _numeric(reward) and reward in (0, 1) and _integer(returncode)
        audit.test(valid_lists and valid_scalars, "public_verifier_schema", "Raw verifier needs binary reward, integer returncode, and component arrays", run_id=identity)
        if not valid_lists or not valid_scalars:
            continue
        components = passed + failed
        audit.test(len(components) == len(set(components)), "public_components_unique", "A verifier component may appear once and cannot both pass and fail", run_id=identity)
        observed_components = bool(components)
        all_passed = bool(passed) and not failed
        stdout = raw.get("stdout")
        pytest_executed = None
        if isinstance(stdout, str) and stdout:
            parsed_passed = re.findall(r"^PASS: (component_\w+)", stdout, re.M)
            parsed_failed = re.findall(r"^FAIL: (component_\w+)", stdout, re.M)
            audit.test(parsed_passed == passed and parsed_failed == failed, "public_components_match_stdout", "Recorded components must match the original verifier stdout", run_id=identity)
            # A Python file that merely defines test_solution can exit zero.
            # Require pytest's final count and duration, not only an exit code.
            pytest_executed = bool(re.search(r"\b[1-9]\d* (?:passed|failed)\b[^\n]*\bin \d+(?:\.\d+)?s\b", stdout))
            audit.test(pytest_executed, "public_pytest_executed", "Public verifier stdout must show at least one actually executed pytest test", run_id=identity)
        else:
            audit.add("warning", "public_pytest_stdout_missing", "Raw stdout is unavailable; actual pytest execution cannot be confirmed", run_id=identity)
        valid_execution = observed_components and pytest_executed is not False
        expected_pass = row.get("status") == "completed" and valid_execution and all_passed and reward == 1 and returncode == 0 and bool((row.get("final_build") or {}).get("success"))
        audit.test(verification.get("passed") is expected_pass, "public_pass_matches_raw_verifier", "verification.passed requires completed execution, a successful final build, and raw all-component success", run_id=identity, expected_passed=expected_pass)
        audit.test(reward == (1 if all_passed else 0), "public_reward_matches_components", "Binary upstream reward must agree with all-component success", run_id=identity)
        for key in ("reward", "components_passed", "components_failed"):
            audit.test(verification.get(key) == raw.get(key), "public_verification_matches_raw", f"verification.{key} must match raw_verifier", run_id=identity)
        if "valid_pytest_execution" in verification and pytest_executed is not None:
            audit.test(verification["valid_pytest_execution"] is valid_execution, "public_execution_flag_matches_evidence", "valid_pytest_execution must agree with recorded execution evidence", run_id=identity)


def _check_summary(report: dict, records: list[dict], audit: _Checks) -> None:
    try:
        from datapatch.evaluation import summarize
        expected = summarize(records)
    except Exception as exc:
        audit.add("failed", "summary_recompute", f"Could not recompute summarize(records): {type(exc).__name__}: {exc}")
        return
    summary = report.get("summary")
    if not isinstance(summary, list) or not all(isinstance(row, dict) and isinstance(row.get("mode"), str) for row in summary):
        audit.add("failed", "summary_schema", "summary must be an array of mode rows")
        return
    modes = [row["mode"] for row in summary]
    audit.test(len(modes) == len(set(modes)), "duplicate_summary_mode", "Summary modes must be unique")
    expected_by_mode = {row["mode"]: row for row in expected}
    actual_by_mode = {row["mode"]: row for row in summary}
    differences = []
    if set(expected_by_mode) != set(actual_by_mode):
        differences.append("Summary mode set differs from recorded trial modes")
    for mode, row in expected_by_mode.items():
        differences.extend(_differences(row, actual_by_mode.get(mode), f"summary.{mode}"))
    audit.test(not differences, "summary_matches_records", "Stored summary must match summarize(records)", differences=differences)


def _source_groups(report: dict, report_path: Path | None) -> dict[Path, dict[str, set[str]]]:
    protocol = report.get("protocol") or {}
    common_hash = protocol.get("source_sha256")
    per_trial = protocol.get("source_sha256_by_trial") or {}
    groups: dict[Path, dict[str, set[str]]] = {}
    base = report_path.parent if report_path is not None else Path.cwd()
    for row in report.get("records", []):
        declared = row.get("source_snapshot") or report.get("source_snapshot") or protocol.get("source_snapshot")
        candidate = Path(str(declared)) if declared else (base / (report_path.stem + "_source.zip") if report_path is not None else None)
        if candidate is None:
            continue
        # Exported packages may keep a zip beside the JSON while an original
        # absolute workspace path is no longer available.
        portable_name = PureWindowsPath(str(declared)).name if declared and "\\" in str(declared) else candidate.name
        sibling = base / portable_name
        if sibling.is_file():
            candidate = sibling
        elif not candidate.is_absolute():
            candidate = base / candidate
        group = groups.setdefault(candidate.resolve(), {"core_hashes": set(), "zip_hashes": set()})
        for value in (common_hash, row.get("source_sha256"), per_trial.get(row.get("run_id"))):
            if isinstance(value, str) and value:
                group["core_hashes"].add(value)
        binary_hash = row.get("source_snapshot_sha256")
        if isinstance(binary_hash, str) and binary_hash:
            group["zip_hashes"].add(binary_hash)
    return groups


def _check_sources(report: dict, report_path: Path | None, audit: _Checks) -> None:
    groups = _source_groups(report, report_path)
    if not groups:
        audit.add("warning", "source_unverifiable", "No source snapshot could be associated with this report")
    for path, expected in groups.items():
        label = str(path)
        if not path.is_file():
            audit.add("warning", "source_snapshot_missing", "Source snapshot unavailable; source binding was not verified", snapshot=label)
            continue
        binary_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        for expected_hash in expected["zip_hashes"]:
            audit.test(binary_hash == expected_hash, "snapshot_zip_hash", "Source zip must match the recorded SHA-256", snapshot=label)
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                manifest_name = next((name for name in ("source-manifest.json", "manifest.json") if name in names), None)
                manifest = json.loads(archive.read(manifest_name)) if manifest_name else None
                if manifest is None:
                    audit.add("warning", "legacy_source_manifest_missing", "Legacy zip has no manifest; verify only the canonical core digest, not per-file manifest claims", snapshot=label)
                elif isinstance(manifest, dict) and isinstance(manifest.get("files"), (list, dict)):
                    declared_files = manifest["files"]
                    items = ([{"path": name, "sha256": digest} for name, digest in declared_files.items()]
                             if isinstance(declared_files, dict) else declared_files)
                    for item in items:
                        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
                            audit.add("failed", "manifest_file_schema", "Known manifest files schema requires string path and sha256", snapshot=label)
                            continue
                        name = item["path"]
                        if name not in names:
                            audit.add("failed", "manifest_file_missing", "Manifest-declared source file is missing", snapshot=label, member=str(name))
                            continue
                        actual = hashlib.sha256(archive.read(name)).hexdigest()
                        audit.test(actual == item.get("sha256"), "manifest_file_hash", "Manifest file content must match its SHA-256", snapshot=label, member=name)
                else:
                    audit.add("warning", "manifest_schema_unverifiable", "Unknown manifest schema; per-file verification unavailable", snapshot=label)
                core_files = sorted(name for name in names if PurePosixPath(name).parent.as_posix() == "src/datapatch" and name.endswith(".py"))
                if not core_files:
                    audit.add("warning", "core_source_unverifiable", "Zip lacks canonical src/datapatch/*.py entries; core hash was not verified", snapshot=label)
                    continue
                digest = hashlib.sha256()
                for name in core_files:
                    digest.update(PurePosixPath(name).name.encode())
                    digest.update(archive.read(name))
                core_hash = digest.hexdigest()
                if isinstance(manifest, dict) and manifest.get("core_source_sha256"):
                    audit.test(core_hash == manifest["core_source_sha256"], "manifest_core_hash", "Manifest core digest must match the actual archived Python files", snapshot=label)
                if expected["core_hashes"]:
                    for expected_hash in expected["core_hashes"]:
                        audit.test(core_hash == expected_hash, "report_source_hash", "Report source hash must match the archived core", snapshot=label)
                else:
                    audit.add("warning", "report_source_hash_missing", "Zip integrity checked but report has no source hash to bind to it", snapshot=label)
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
            audit.add("failed", "snapshot_read_error", f"Cannot verify source archive: {type(exc).__name__}: {exc}", snapshot=label)


def audit_report(report: dict | Path | str, *, report_path: Path | None = None) -> dict:
    """Audit one report; dictionary inputs may supply a path for source lookup."""
    audit = _Checks()
    if isinstance(report, (str, Path)):
        report_path = Path(report).resolve()
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            audit.add("failed", "report_read_error", f"Cannot read report: {type(exc).__name__}: {exc}")
            return audit.result()
    if not isinstance(report, dict) or not isinstance(report.get("records"), list) or not all(isinstance(row, dict) for row in report.get("records", [])):
        audit.add("failed", "report_schema", "Report must contain a records array of trial objects")
        return audit.result()
    records = report["records"]
    for name, check in (
        ("protocol", lambda: _check_matrix(report, records, audit)),
        ("records", lambda: _check_records(records, audit)),
        ("public_verifiers", lambda: _check_public_verifiers(report, records, audit)),
        ("summary", lambda: _check_summary(report, records, audit)),
        ("source", lambda: _check_sources(report, report_path, audit)),
    ):
        try:
            check()
        except (TypeError, AttributeError, ValueError, KeyError, OverflowError, OSError) as exc:
            audit.add("failed", "audit_check_error", f"{name} check could not complete: {type(exc).__name__}: {exc}")
    return audit.result()


def audit_reports(paths: list[Path], *, include_unamended: bool = False) -> dict:
    """Audit selected reports, explicitly listing historical backups excluded."""
    aggregate = _Checks()
    reports = []
    excluded = []
    for path in sorted(set(Path(item).resolve() for item in paths)):
        if path.stem.endswith("_unamended") and not include_unamended:
            reason = "Historical unamended backup excluded by explicit default policy; use --include-unamended to audit it"
            excluded.append({"report": str(path), "reason": reason})
            aggregate.add("warning", "unamended_report_excluded", reason, report=str(path))
            continue
        result = audit_report(path)
        reports.append({"report": str(path), **result})
        for key in ("errors", "warnings", "checks"):
            getattr(aggregate, key).extend({"report": str(path), **item} for item in result[key])
    if not reports:
        aggregate.add("failed", "no_reports", "No non-excluded evaluation reports were audited")
    return {**aggregate.result(), "checked_report_count": len(reports), "reports": reports, "excluded_reports": excluded}
