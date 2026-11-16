from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from datapatch.evaluation import summarize
from datapatch.audit import audit_report, audit_reports

ROOT = Path(__file__).resolve().parents[1]
def example_report() -> dict:
    rows = [{"run_id": "trial-1", "task_id": "one", "mode": "verified", "repeat": 0, "status": "completed", "verification": {"passed": True}, "final_build": {"success": True}, "metrics": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "model_calls": 2, "tool_calls": 3, "estimated_cost_usd": 0.01, "elapsed_seconds": 3.2}}]
    return {"status": "completed", "planned_trials": 1, "protocol": {"task_ids": ["one"], "modes": ["verified"], "repeats": 1}, "records": rows, "summary": summarize(rows)}


def error_codes(result: dict) -> set[str]:
    return {item["code"] for item in result["errors"]}


def test_valid_report_warns_about_unavailable_source_without_claiming_source_pass():
    result = audit_report(example_report())
    assert result["passed"] is True
    assert any(item["code"] == "source_unverifiable" for item in result["warnings"])
    assert not any(item["code"] == "report_source_hash" and item["status"] == "passed" for item in result["checks"])


def test_tampered_summary_is_detected():
    report = example_report()
    report["summary"][0]["total_tokens"] += 1
    assert "summary_matches_records" in error_codes(audit_report(report))


def test_duplicate_run_id_and_duplicate_protocol_trial_are_detected():
    report = example_report()
    report["records"].append(copy.deepcopy(report["records"][0]))
    report["summary"] = summarize(report["records"])
    codes = error_codes(audit_report(report))
    assert {"duplicate_run_id", "duplicate_trial", "trial_count"} <= codes


def test_missing_matrix_trial_is_detected_even_if_summary_is_self_consistent():
    report = example_report()
    report["protocol"]["task_ids"].append("two")
    report["planned_trials"] = 2
    assert {"missing_trials", "trial_count"} <= error_codes(audit_report(report))


@pytest.mark.parametrize("field", ["status", "final_build"])
def test_false_pass_after_failed_execution_or_build_is_rejected(field):
    report = example_report()
    report["records"][0][field] = "failed" if field == "status" else {"success": False}
    report["summary"] = summarize(report["records"])
    codes = error_codes(audit_report(report))
    assert ("passed_incomplete_execution" if field == "status" else "passed_failed_build") in codes


@pytest.mark.parametrize("tamper,code", [("tokens", "token_sum"), ("cost", "nonnegative_measure")])
def test_inconsistent_tokens_and_negative_cost_are_rejected(tamper, code):
    report = example_report()
    if tamper == "tokens":
        report["records"][0]["metrics"]["total_tokens"] = 1
    else:
        report["records"][0]["metrics"]["estimated_cost_usd"] = -0.1
    report["summary"] = summarize(report["records"])
    assert code in error_codes(audit_report(report))


def make_snapshot(path: Path, *, manifest: bool | str) -> str:
    name, data = "src/datapatch/example.py", b"VALUE = 1\n"
    digest = hashlib.sha256(b"example.py" + data).hexdigest()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, data)
        if manifest:
            file_hash = hashlib.sha256(data).hexdigest()
            files = {name: file_hash} if manifest == "dict" else [{"path": name, "sha256": file_hash}]
            archive.writestr("source-manifest.json", json.dumps({"core_source_sha256": digest, "files": files}))
    return digest


@pytest.mark.parametrize("manifest", [True, "dict", False])
def test_source_hash_can_be_verified_with_manifest_or_legacy_zip(tmp_path, manifest):
    report = example_report()
    path = tmp_path / "example_source.zip"
    report["protocol"]["source_sha256"] = make_snapshot(path, manifest=manifest)
    report["source_snapshot"] = str(path)
    result = audit_report(report)
    assert result["passed"]
    assert any(item["code"] == "report_source_hash" and item["status"] == "passed" for item in result["checks"])
    if not manifest:
        assert any(item["code"] == "legacy_source_manifest_missing" for item in result["warnings"])
    else:
        assert any(item["code"] == "manifest_file_hash" and item["status"] == "passed" for item in result["checks"])


def test_dictionary_manifest_hash_is_actually_checked(tmp_path):
    report = example_report()
    path = tmp_path / "tampered_source.zip"
    data = b"VALUE = 1\n"
    report["protocol"]["source_sha256"] = hashlib.sha256(b"example.py" + data).hexdigest()
    report["source_snapshot"] = str(path)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("src/datapatch/example.py", data)
        archive.writestr("source-manifest.json", json.dumps({"files": {"src/datapatch/example.py": "0" * 64}}))
    assert "manifest_file_hash" in error_codes(audit_report(report))


def public_report(*, passed: bool) -> dict:
    report = example_report()
    report["dataset"] = "snowflake-data-eng-bench/native-public-development-subset"
    component = "component_1_model_compiles"
    raw = {"mode": "native-path-adapted-upstream-verifier", "reward": 1.0 if passed else 0.0, "returncode": 0 if passed else 1,
           "components_passed": [component] if passed else [], "components_failed": [] if passed else [component],
           "stdout": f"{'PASS' if passed else 'FAIL'}: {component}\n1 {'passed' if passed else 'failed'} in 0.25s\n"}
    report["records"][0]["raw_verifier"] = raw
    report["records"][0]["verification"] = {key: raw[key] for key in ("reward", "components_passed", "components_failed")}
    report["records"][0]["verification"].update({"passed": passed, "valid_pytest_execution": True})
    report["summary"] = summarize(report["records"])
    return report


@pytest.mark.parametrize("passed", [True, False])
def test_public_grade_consistent_with_actual_raw_verifier(passed):
    assert audit_report(public_report(passed=passed))["passed"]


@pytest.mark.parametrize("passed", [True, False])
def test_plain_pytest_public_grading_is_audited(passed):
    report = public_report(passed=passed)
    row = report["records"][0]
    counts = {"passed": 11 if passed else 0, "failed": 0 if passed else 11, "errors": 0, "skipped": 0}
    row["raw_verifier"].update({"grading_protocol": "pytest_exit_status", "pytest_counts": counts,
                               "scoring_source_sha256": "a" * 64, "components_passed": [], "components_failed": [],
                               "stdout": f"11 {'passed' if passed else 'failed'} in 0.50s\n"})
    row["verification"].update({"components_passed": [], "components_failed": []})
    assert audit_report(report)["passed"]
    row["raw_verifier"]["pytest_counts"]["passed"] += 1
    assert "public_pytest_counts_match_stdout" in error_codes(audit_report(report))


@pytest.mark.parametrize("incomplete", ["execution", "build"])
def test_raw_correct_output_does_not_override_failed_delivery(incomplete):
    report = public_report(passed=True)
    row = report["records"][0]
    if incomplete == "execution":
        row["status"] = "failed"
    else:
        row["final_build"]["success"] = False
    row["verification"]["passed"] = False
    report["summary"] = summarize(report["records"])
    assert audit_report(report)["passed"]


def test_public_false_pass_does_not_trust_hand_edited_verification():
    report = public_report(passed=False)
    report["records"][0]["verification"]["passed"] = True
    report["summary"] = summarize(report["records"])
    assert "public_pass_matches_raw_verifier" in error_codes(audit_report(report))


def test_public_zero_exit_without_executed_pytest_cannot_pass():
    report = public_report(passed=True)
    report["records"][0]["raw_verifier"]["stdout"] = "PASS: component_1_model_compiles\n"
    codes = error_codes(audit_report(report))
    assert {"public_pytest_executed", "public_pass_matches_raw_verifier"} <= codes


def test_public_components_cannot_be_omitted_from_raw_stdout():
    report = public_report(passed=True)
    report["records"][0]["raw_verifier"]["stdout"] += "FAIL: component_2_row_count\n"
    assert "public_components_match_stdout" in error_codes(audit_report(report))


def test_public_missing_raw_is_warning_without_claiming_test_execution():
    report = public_report(passed=True)
    del report["records"][0]["raw_verifier"]
    result = audit_report(report)
    assert any(item["code"] == "public_verifier_unavailable" for item in result["warnings"])
    assert not any(item["code"] == "public_pytest_executed" for item in result["checks"])


def test_public_missing_stdout_does_not_claim_execution_was_verified():
    report = public_report(passed=True)
    del report["records"][0]["raw_verifier"]["stdout"]
    result = audit_report(report)
    assert any(item["code"] == "public_pytest_stdout_missing" for item in result["warnings"])
    assert not any(item["code"] == "public_execution_flag_matches_evidence" for item in result["checks"])


def test_mismatched_source_hash_is_an_error(tmp_path):
    report = example_report()
    path = tmp_path / "example_source.zip"
    make_snapshot(path, manifest=True)
    report["source_snapshot"] = str(path)
    report["protocol"]["source_sha256"] = "0" * 64
    assert "report_source_hash" in error_codes(audit_report(report))


def test_exported_windows_source_path_resolves_to_portable_sibling_zip(tmp_path):
    report = example_report()
    path = tmp_path / "example_source.zip"
    report["protocol"]["source_sha256"] = make_snapshot(path, manifest="dict")
    report["source_snapshot"] = r"Z:\original-workspace\example_source.zip"
    result = audit_report(report, report_path=tmp_path / "example.json")
    assert result["passed"]
    assert any(item["code"] == "report_source_hash" and item["status"] == "passed" for item in result["checks"])


def test_history_is_explicitly_excluded_but_include_history_exposes_bad_grade(tmp_path):
    report = example_report()
    current = tmp_path / "example.json"
    current.write_text(json.dumps(report), encoding="utf-8")
    report["records"][0]["status"] = "failed"
    report["summary"] = summarize(report["records"])
    history = tmp_path / "example_unamended.json"
    history.write_text(json.dumps(report), encoding="utf-8")
    result = audit_reports([current, history])
    assert result["passed"] and len(result["excluded_reports"]) == 1
    assert "passed_incomplete_execution" in error_codes(audit_reports([current, history], include_unamended=True))


def test_empty_selection_is_not_reported_as_a_pass():
    assert "no_reports" in error_codes(audit_reports([]))


def test_real_local_reports_are_audited_read_only():
    # Other workers may still be writing a running report. The frozen completed
    # reports are the read-only regression inputs for this test.
    paths = [path for path in (ROOT / "artifacts/evaluations").glob("*.json") if json.loads(path.read_text(encoding="utf-8")).get("status") == "completed"]
    if not paths:
        pytest.skip("No saved local reports")
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    result = audit_reports(paths)
    assert result["passed"], result["errors"]
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
