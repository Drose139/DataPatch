"""Replay exports are checked against synthetic files, never model APIs."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
import uuid

import pytest


spec = importlib.util.spec_from_file_location(
    "export_public_recordings", Path(__file__).parents[1] / "scripts/export_public_recordings.py"
)
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def test_public_business_contract_assistance_is_preserved(public_files):
    files = public_files
    data = json.loads(files["agent"].read_text(encoding="utf-8"))
    data["public_contracts"] = {"contract_origin": "project_configuration", "reference_solution": False}
    data["target_start"] = {"exists": True, "sha256": "candidate-before-repair"}
    files["agent"].write_text(json.dumps(data), encoding="utf-8")
    record = exporter.convert_record(files["report"]["records"][0], files["report"], files["report_path"], files["root"])
    assert record["public_contracts"] == data["public_contracts"]
    assert record["target_start"] == data["target_start"]
    assert record["verification"]["passed"] is False


@pytest.fixture
def public_files(tmp_path):
    root = tmp_path / "project"
    agent = root / "external/native-results/arbitrary-case-verified.json"
    verifier = root / "external/public-verifiers/unlisted-public-task/arbitrary-case-evaluation.json"
    instruction = root / "external/native-cases/arbitrary-case/instruction.md"
    report_path = root / "artifacts/evaluations/public-test.json"
    for path in (agent, verifier, instruction, report_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    instruction.write_text("# Repair an arbitrary public model\n\nPreserve every source row.\n", encoding="utf-8")
    events = [
        {"type": "model", "name": "deepseek-v4-pro", "content": "Inspect the public contract", "timestamp": "2026-10-25T12:00:00Z",
         "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}},
        {"type": "tool", "name": "read_file", "arguments": {"path": "project/models/report.sql"},
         "result": {"content": "select 1", "project": str(root / "external/native-cases/arbitrary-case/project")}},
        {"type": "review", "name": "candidate_semantic_review", "result": {"verdict": "revise", "advisory_only": True}},
        {"type": "final", "content": "Budget exhausted", "stop_reason": "step_limit"},
    ]
    agent.with_suffix(".jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    patch = "--- a/project/models/report.sql\n+++ b/project/models/report.sql\n-select 0\n+select 1\n"
    agent.with_suffix(".patch").write_text(patch, encoding="utf-8")
    metrics = {"model_calls": 1, "tool_calls": 1, "prompt_tokens": 100, "completion_tokens": 20,
               "total_tokens": 120, "estimated_cost_usd": 0.000211, "elapsed_seconds": 3.25}
    agent_payload = {"task_id": "unlisted-public-task", "mode": "verified", "model": "deepseek-v4-pro",
                     "commit": "fixed-upstream-commit", "events": str(agent.with_suffix(".jsonl")),
                     "result": {"metrics": metrics, "candidate_review": {"verdict": "revise", "patch_changed_since_review": True},
                                "final_answer": "Actual handoff", "stop_reason": "step_limit"}}
    agent.write_text(json.dumps(agent_payload), encoding="utf-8")
    original_verifier = {"task_id": "unlisted-public-task", "returncode": 1, "reward": 0,
                         "components_passed": ["component_1_model_compiles"],
                         "components_failed": ["component_2_row_coverage"],
                         "stdout": "PASS: component_1_model_compiles\nFAIL: component_2_row_coverage\n1 failed in 0.25s",
                         "stderr": ""}
    verifier.write_text(json.dumps(original_verifier), encoding="utf-8")
    source_record = {"run_id": "arbitrary-case-verified", "task_id": "unlisted-public-task", "mode": "verified",
                     "status": "completed", "model": "deepseek-v4-pro", "metrics": metrics,
                     "verification": {"passed": False, "reward": 0, "components_passed": original_verifier["components_passed"],
                                      "components_failed": original_verifier["components_failed"], "valid_pytest_execution": True},
                     "final_build": {"success": True}, "agent_report": str(agent), "verifier_report": str(verifier)}
    report = {"status": "completed", "name": "public-test", "records": [source_record],
              "upstream_repository": "https://github.com/example/public-benchmark", "upstream_commit": "fixed-upstream-commit"}
    report_path.write_text(json.dumps(report), encoding="utf-8")
    # These private/executable artifacts must not be opened during export.
    (instruction.parent / "database").mkdir()
    (instruction.parent / "database/retail.duckdb").write_bytes(b"do-not-read-database")
    (instruction.parent / "solution").mkdir()
    (instruction.parent / "solution/solve.sql").write_text("private-reference-answer", encoding="utf-8")
    return {"root": root, "report_path": report_path, "report": report, "agent": agent,
            "verifier": verifier, "instruction": instruction, "events": events, "patch": patch,
            "metrics": metrics, "raw_verifier": original_verifier}


def test_export_preserves_real_events_verdict_patch_and_cost_without_execution(public_files, monkeypatch):
    files = public_files
    root = files["root"]
    reads = []
    original_read = Path.read_text

    def tracked_read(path, *args, **kwargs):
        reads.append(path)
        return original_read(path, *args, **kwargs)

    def no_network(*args, **kwargs):
        pytest.fail("An offline export must not create a network connection")

    monkeypatch.setattr(Path, "read_text", tracked_read)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    original_sources = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    output_paths = exporter.export_reports([files["report_path"]], project_root=root)

    expected_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "datapatch:public-native:arbitrary-case-verified"))
    assert output_paths == [root / "examples/recorded_runs" / (expected_id + ".json")]
    assert set(reads) == {files["report_path"], files["agent"], files["agent"].with_suffix(".jsonl"),
                          files["agent"].with_suffix(".patch"), files["verifier"], files["instruction"]}
    record = json.loads(output_paths[0].read_text(encoding="utf-8"))
    assert record["run_id"] == expected_id and uuid.UUID(expected_id).version == 5
    assert record["source_run_id"] == "arbitrary-case-verified"
    assert record["provider"] == "deepseek" and record["model"] == "deepseek-v4-pro"
    assert record["status"] == "completed"
    assert record["verification"]["passed"] is False
    assert record["verification"]["reward"] == 0
    assert record["metrics"] == files["metrics"]
    assert record["diff"] == files["patch"]
    assert record["raw_verifier"] == files["raw_verifier"]
    assert record["candidate_review"]["patch_changed_since_review"] is True
    assert [event["seq"] for event in record["events"]] == [1, 2, 3, 4]
    assert [event["type"] for event in record["events"]] == [event["type"] for event in files["events"]]
    for index in (0, 2, 3):
        assert record["events"][index] == {**files["events"][index], "seq": index + 1}
    assert record["events"][1]["arguments"] == files["events"][1]["arguments"]
    assert record["events"][1]["result"]["content"] == files["events"][1]["result"]["content"]
    assert record["events"][0]["timestamp"] == "2026-10-25T12:00:00Z"
    assert all("timestamp" not in event for event in record["events"][1:])
    assert "started_at" not in record and "finished_at" not in record
    assert "data_evidence" not in record
    assert record["task"]["title"] == "公开项目 · Repair an arbitrary public model"
    assert "Preserve every source row" in record["task"]["description"]
    assert "已记录真实公开运行回放" in record["recording_source"]
    assert all(value.startswith("$PROJECT") for value in record["source_artifacts"].values())
    assert record["events"][1]["result"]["project"].startswith("$PROJECT")
    assert [(check["name"], check["passed"]) for check in record["checks"]] == [
        ("final_build_success", True), ("component_1_model_compiles", True), ("component_2_row_coverage", False)]
    assert str(root) not in json.dumps(record)
    assert "private-reference-answer" not in json.dumps(record)
    assert all(path.read_bytes() == content for path, content in original_sources.items())
    first_export = output_paths[0].read_bytes()
    exporter.export_reports([files["report_path"]], project_root=root)
    assert output_paths[0].read_bytes() == first_export


def test_execution_failure_and_failed_final_build_are_not_upgraded(public_files):
    files = public_files
    report = deepcopy(files["report"])
    report["records"][0].update({"status": "failed", "final_build": {"success": False}, "error": "Observed execution failure"})
    files["report_path"].write_text(json.dumps(report), encoding="utf-8")

    path = exporter.export_reports([files["report_path"]], project_root=files["root"])[0]

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["status"] == "failed"
    assert record["verification"]["passed"] is False
    assert record["checks"][0]["passed"] is False
    assert record["error"] == "Observed execution failure"


def test_success_record_preserves_the_saved_upstream_verdict(public_files):
    files = public_files
    report = deepcopy(files["report"])
    verification = report["records"][0]["verification"]
    verification.update({"passed": True, "reward": 1, "components_passed": ["component_1_model_compiles", "component_2_row_coverage"],
                         "components_failed": []})
    verifier = deepcopy(files["raw_verifier"])
    verifier.update({"returncode": 0, "reward": 1, "components_passed": verification["components_passed"],
                     "components_failed": [], "stdout": "PASS: component_1_model_compiles\nPASS: component_2_row_coverage\n1 passed in 0.25s"})
    files["report_path"].write_text(json.dumps(report), encoding="utf-8")
    files["verifier"].write_text(json.dumps(verifier), encoding="utf-8")

    path = exporter.export_reports([files["report_path"]], project_root=files["root"])[0]

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["status"] == "completed" and record["verification"]["passed"] is True
    assert record["verification"]["reward"] == 1
    assert all(check["passed"] is True for check in record["checks"])
    assert record["raw_verifier"] == verifier


def test_relocated_project_paths_and_cli_run_selection(public_files, capsys):
    files = public_files
    report = deepcopy(files["report"])
    record = report["records"][0]
    record["agent_report"] = "$PROJECT/external/native-results/arbitrary-case-verified.json"
    record["verifier_report"] = "C:/previous-machine/project/external/public-verifiers/unlisted-public-task/arbitrary-case-evaluation.json"
    files["report_path"].write_text(json.dumps(report), encoding="utf-8")

    assert exporter.main([str(files["report_path"]), "--project-root", str(files["root"]),
                          "--run-id", "arbitrary-case-verified"]) == 0
    assert "No model, database or verifier was executed" in capsys.readouterr().out
    target = files["root"] / "examples/recorded_runs" / (exporter.archived_run_id("arbitrary-case-verified") + ".json")
    assert json.loads(target.read_text(encoding="utf-8"))["source_artifacts"]["verifier_report"].startswith("$PROJECT")


def test_missing_inputs_or_incomplete_reports_do_not_create_recordings(public_files):
    files = public_files
    report = deepcopy(files["report"])
    report["status"] = "running"
    files["report_path"].write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="Only completed"):
        exporter.export_reports([files["report_path"]], project_root=files["root"])
    assert not (files["root"] / "examples/recorded_runs").exists()
    report["status"] = "completed"
    files["report_path"].write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="not found"):
        exporter.export_reports([files["report_path"]], project_root=files["root"], run_ids={"not-recorded"})
    files["agent"].with_suffix(".patch").unlink()
    with pytest.raises(FileNotFoundError):
        exporter.export_reports([files["report_path"]], project_root=files["root"])
    assert not (files["root"] / "examples/recorded_runs").exists()


@pytest.mark.parametrize("counts,expected_passed", [
    ({"passed": 11, "failed": 0, "errors": 0, "skipped": 0}, True),
    ({"passed": 10, "failed": 1, "errors": 0, "skipped": 0}, False),
    ({"passed": 0, "failed": 0, "errors": 1, "skipped": 0}, False),
    ({"passed": 10, "failed": 0, "errors": 0, "skipped": 1}, False),
])
def test_plain_pytest_execution_is_visible_without_inventing_components(public_files, counts, expected_passed):
    files = public_files
    report = deepcopy(files["report"])
    report["records"][0]["verification"] = {"passed": expected_passed, "reward": int(expected_passed), "valid_pytest_execution": True}
    verifier = {"task_id": "unlisted-public-task", "grading_protocol": "pytest_exit_status", "pytest_counts": counts,
                "pytest_returncode": 0 if expected_passed else 1, "returncode": 0 if expected_passed else 1,
                "reward": int(expected_passed), "scoring_source": "https://example.test/pinned/test.sh",
                "scoring_source_sha256": "a" * 64, "stdout": "Original pytest execution output", "stderr": ""}
    files["report_path"].write_text(json.dumps(report), encoding="utf-8")
    files["verifier"].write_text(json.dumps(verifier), encoding="utf-8")

    target = exporter.export_reports([files["report_path"]], project_root=files["root"])[0]

    record = json.loads(target.read_text(encoding="utf-8"))
    assert record["verification"]["passed"] is expected_passed
    assert record["raw_verifier"] == verifier
    checks = {check["name"]: check for check in record["checks"]}
    assert checks["pytest_executed_tests"]["actual"] == counts["passed"] + counts["failed"]
    assert checks["pytest_executed_tests"]["passed"] is (counts["passed"] + counts["failed"] > 0)
    for key, name in (("failed", "pytest_no_failures"), ("errors", "pytest_no_errors"), ("skipped", "pytest_no_skips")):
        assert checks[name]["actual"] == counts[key]
        assert checks[name]["passed"] is (counts[key] == 0)
    assert checks["pytest_exit_status"]["actual"] == verifier["pytest_returncode"]
    assert not any(name.startswith("component_") for name in checks)


def test_account_failure_reaches_run_error_even_when_original_pytest_passes(public_files):
    files = public_files
    report = deepcopy(files["report"])
    source = report["records"][0]
    source.update({"status": "failed", "execution_error": "Model API HTTP 402: Insufficient Balance",
                   "error_type": "ModelError", "failure_category": "infrastructure: model API HTTP 402 insufficient balance"})
    source["verification"] = {"passed": False, "reward": 1, "valid_pytest_execution": True}
    verifier = {"grading_protocol": "pytest_exit_status", "pytest_counts": {"passed": 11, "failed": 0, "errors": 0, "skipped": 0},
                "pytest_returncode": 0, "returncode": 0, "reward": 1, "stdout": "11 passed in 0.2s", "stderr": ""}
    files["report_path"].write_text(json.dumps(report), encoding="utf-8")
    files["verifier"].write_text(json.dumps(verifier), encoding="utf-8")

    path = exporter.export_reports([files["report_path"]], project_root=files["root"])[0]

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["status"] == "failed" and record["verification"]["passed"] is False
    assert record["raw_verifier"]["reward"] == 1
    assert record["execution_error"] == source["execution_error"]
    assert record["failure_category"] == source["failure_category"]
    assert record["error_type"] == "ModelError"
    assert "HTTP 402" in record["error"] and "Insufficient Balance" in record["error"]
    assert "infrastructure" in record["error"]
