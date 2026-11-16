from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("reviewed_recordings", Path(__file__).resolve().parents[1] / "scripts/export_reviewed_recordings.py")
recordings = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(recordings)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def write_bytes(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return hashlib.sha256(value).hexdigest()


@pytest.fixture
def acceptance(tmp_path):
    snapshot = tmp_path / "external/public-snapshot"
    database = snapshot / "base-image/database/retail.duckdb"
    database_hash = write_bytes(database, b"database is only hashed, never opened")
    tasks = ("public-create-any-name", "public-fix-any-name")
    lock = {"repository": "example/public", "commit": "pinned", "tasks": list(tasks),
            "database": {"bytes": database.stat().st_size, "sha256": database_hash}, "files": []}
    rows = []
    for index, task in enumerate(tasks):
        model_path = "models/marts/" + task + ".sql"
        instruction = snapshot / "tasks" / task / "instruction.md"
        write_bytes(instruction, ("# Original public task " + task + "\nPublic requirements.").encode())
        initial_paths = [instruction]
        if index:
            buggy = snapshot / "tasks" / task / "environment/data" / Path(model_path).name
            write_bytes(buggy, b"select 1 / 0 as broken\n")
            initial_paths.append(buggy)
        inputs = [{"path": p.relative_to(snapshot).as_posix(), "sha256": recordings._sha256(p), "bytes": p.stat().st_size} for p in initial_paths]
        lock["files"].extend(inputs)
        patch = tmp_path / "examples/public_fixes" / (task + ".sql")
        patch_hash = write_bytes(patch, b"-- operator_reviewed\nselect 42 as fixed\n")
        case = tmp_path / "external/fresh-cases" / task
        write_bytes(case / "project" / model_path, patch.read_bytes())
        preparation = {"task_id": task, "upstream_commit": "pinned", "task_type": "fix-model" if index else "create-model", "project_dir": str(case / "project")}
        write_json(case / "native-case.json", preparation)
        build = {"success": True, "target_model_success": True, "stdout": "ACTUAL SAVED BUILD", "returncode": 0}
        archive = tmp_path / "artifacts/acceptance/evidence" / task
        build_path = archive / "build.json"
        write_json(build_path, build)
        verifier = archive / "verifier/result.json"
        original_hash = write_bytes(verifier.parent / "test_outputs.original.py", b"ORIGINAL PUBLIC TEST BYTES")
        adapted_hash = write_bytes(verifier.parent / ("test_outputs_" + task.replace("-", "_") + ".py"), b"PATH ADAPTED ORIGINAL TEST BYTES")
        raw = {"returncode": 0, "reward": 1.0, "stdout": "11 passed in 1.23s", "original_sha256": original_hash,
               "adapted_sha256": adapted_hash, "components_passed": [], "components_failed": [], "grading_protocol": "pytest_exit_status",
               "pytest_returncode": 0, "pytest_counts": {"passed": 11, "failed": 0, "errors": 0, "skipped": 0},
               "scoring_source_sha256": write_bytes(verifier.parent / "test.original.sh", b"ORIGINAL PUBLIC SCORING BYTES")}
        if index:
            raw.update({"grading_protocol": "component_reward_json", "components_passed": ["component_real_1", "component_real_2"]})
        write_json(verifier, raw)
        rows.append({"task_id": task, "patch_origin": "operator_reviewed", "zero_api_calls": True,
                     "patch_source": str(patch), "patch_sha256": patch_hash, "applied_patch_sha256": patch_hash,
                     "model_path": model_path, "case_directory": str(case), "status": "completed", "build": build,
                     "verification": {"passed": True, "original_tests_passed": True, "reward": 1.0}, "errors": [],
                     "input_files": inputs, "preparation": preparation, "elapsed_seconds": 5.5,
                     "artifacts": {"build_report": str(build_path), "verifier_report": str(verifier)}, "raw_verifier": raw})
    lock_path = snapshot / "snapshot-lock.json"
    write_json(lock_path, lock)
    report = {"type": "reviewed_patch_acceptance", "name": "actual-reviewed-acceptance", "patch_origin": "operator_reviewed",
              "zero_model_api_calls": True, "planned_tasks": 2, "status": "completed", "protocol": {"task_ids": list(tasks)},
              "input_snapshot": {"repository": "example/public", "commit": "pinned", "snapshot_lock": str(lock_path),
                                 "snapshot_lock_sha256": recordings._sha256(lock_path), "database_sha256": database_hash,
                                 "database_bytes": database.stat().st_size}, "records": rows, "summary": {"accepted": 2}}
    path = tmp_path / "results/acceptance/actual-reviewed-acceptance.json"
    write_json(path, report)
    return tmp_path, path, report


def test_exports_real_artifacts_with_zero_model_metrics_and_explicit_reviewed_provenance(acceptance):
    root, path, report = acceptance
    paths, audit = recordings.export_report(path, project_root=root)
    assert audit["passed"] and audit["input_files_checked"] == 3
    assert len(paths) == 2
    for target, row in zip(paths, report["records"]):
        run = json.loads(target.read_text(encoding="utf-8"))
        assert run["provider"] == "operator_reviewed" and run["mode"] == "reviewed_patch" and run["model"] == "未调用模型"
        assert "不属于自主 Agent 成绩" in run["recording_source"]
        assert run["metrics"] == {"elapsed_seconds": 5.5, "model_calls": 0, "tool_calls": 0, "prompt_tokens": 0,
                                  "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0}
        assert run["final_build"] == row["build"] and run["raw_verifier"] == row["raw_verifier"]
        assert run["verification"]["passed"] is True and "data_evidence" not in run
        assert "final_dependency_build" not in run
        assert not any(check["name"].startswith("dependency_") for check in run["checks"])
        assert all(event["type"] != "model" and "timestamp" not in event for event in run["events"])
        assert "started_at" not in run and "finished_at" not in run
        assert str(root) not in target.read_text(encoding="utf-8") and "$PROJECT" in str(run["source_artifacts"])
        assert "Original public task" in run["task"]["title"] and "Public requirements." in run["task"]["description"]
    created, fixed = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    assert "--- /dev/null" in created["diff"] and "+select 42 as fixed" in created["diff"]
    assert "-select 1 / 0 as broken" in fixed["diff"] and "+select 42 as fixed" in fixed["diff"]
    assert any(c["name"] == "component_real_2" for c in fixed["checks"])
    assert next(c for c in created["checks"] if c["name"] == "pytest_executed_tests")["actual"] == 11


def test_failed_original_pytest_remains_failed_not_upgraded_by_successful_build(acceptance):
    root, path, report = acceptance
    row = report["records"][0]
    row["raw_verifier"].update({"returncode": 1, "reward": 0.0, "pytest_returncode": 1,
                               "stdout": "8 passed, 3 failed in 1.23s", "pytest_counts": {"passed": 8, "failed": 3, "errors": 0, "skipped": 0}})
    row["verification"].update({"passed": False, "original_tests_passed": False, "reward": 0.0})
    report["summary"]["accepted"] = 1
    write_json(Path(row["artifacts"]["verifier_report"]), row["raw_verifier"])
    write_json(path, report)
    paths, _ = recordings.export_report(path, project_root=root)
    run = json.loads(paths[0].read_text(encoding="utf-8"))
    assert run["status"] == "completed" and run["verification"]["passed"] is False
    assert next(c for c in run["checks"] if c["name"] == "pytest_no_failures")["actual"] == 3
    assert "未通过" in run["final_answer"]


def attach_dependency(row, *, success=True, target_success=True):
    dependency = {"success": success, "target_model_success": target_success,
                  "stdout": "ACTUAL SAVED ANCESTOR RUN", "returncode": 0 if success else 1}
    artifact = Path(row["artifacts"]["build_report"]).with_name("dependency_build.json")
    row["dependency_build"] = dependency
    row["artifacts"]["dependency_build_report"] = str(artifact)
    row["verification"]["dependency_build_success"] = success and target_success
    write_json(artifact, dependency)
    return artifact


def test_dependency_artifact_is_audited_and_shown_as_an_acceptance_gate(acceptance):
    root, path, report = acceptance
    row = report["records"][0]
    dependency_path = attach_dependency(row)
    write_json(path, report)
    paths, audit = recordings.export_report(path, project_root=root)
    run = json.loads(paths[0].read_text(encoding="utf-8"))
    assert run["final_dependency_build"] == row["dependency_build"]
    assert run["verification"]["dependency_build_success"] is True
    assert next(check for check in run["checks"] if check["name"] == "dependency_build_success")["actual"] is True
    assert next(check for check in run["checks"] if check["name"] == "dependency_target_model_success")["actual"] is True
    assert run["verification"]["checks"] == run["checks"]
    assert audit["records"][0]["dependency_build_report_sha256"] == recordings._sha256(dependency_path)
    assert run["events"][1]["arguments"]["select"].startswith("+")
    assert [event["seq"] for event in run["events"]] == list(range(1, len(run["events"]) + 1))


@pytest.mark.parametrize("target_success", [False, True])
def test_failed_or_missing_target_dependency_remains_failed_despite_passing_target_and_tests(acceptance, target_success):
    root, path, report = acceptance
    row = report["records"][0]
    attach_dependency(row, success=not target_success, target_success=target_success)
    row["verification"]["passed"] = False
    report["summary"]["accepted"] = 1
    write_json(path, report)
    paths, _ = recordings.export_report(path, project_root=root)
    run = json.loads(paths[0].read_text(encoding="utf-8"))
    assert run["final_build"]["success"] is True and run["raw_verifier"]["reward"] == 1
    assert run["verification"]["passed"] is False
    assert run["verification"]["dependency_build_success"] is False
    assert next(check for check in run["checks"] if check["name"] == "dependency_build_success")["actual"] is False


@pytest.mark.parametrize("corruption", ["artifact", "missing_artifact", "target_verdict", "acceptance_verdict"])
def test_dependency_evidence_conflicts_are_rejected_before_writing_recordings(acceptance, corruption):
    root, path, report = acceptance
    row = report["records"][0]
    dependency_path = attach_dependency(row)
    if corruption == "artifact":
        write_json(dependency_path, {**row["dependency_build"], "stdout": "ALTERED RUN"})
    elif corruption == "missing_artifact":
        row["artifacts"].pop("dependency_build_report")
    elif corruption == "target_verdict":
        row["dependency_build"]["target_model_success"] = False
        write_json(dependency_path, row["dependency_build"])
    else:
        attach_dependency(row, success=False)
    write_json(path, report)
    with pytest.raises(ValueError, match="[Dd]ependency|Acceptance verdict"):
        recordings.export_report(path, project_root=root)
    assert not (root / "examples/recorded_runs").exists()


def apply_upstream_policy(report, *, failed_build=True):
    report["protocol"].update({"acceptance_policy": "upstream_harness", "build_required": False})
    for index, row in enumerate(report["records"]):
        attach_dependency(row)
        if failed_build and index == 0:
            row["build"]["success"] = False
            row["build"]["stdout"] += "\n177 original null IDs; 1308 original duplicate groups"
        write_json(Path(row["artifacts"]["build_report"]), row["build"])
        row["verification"].update({"acceptance_policy": "upstream_harness", "build_required": False,
                                     "target_materialization_success": True})
        row["project_quality"] = {"build": dict(row["build"]), "build_required": False}


def test_upstream_policy_exports_true_materialization_and_preserves_false_build_and_extra_quality(acceptance):
    root, path, report = acceptance
    apply_upstream_policy(report)
    write_json(path, report)
    paths, _ = recordings.export_report(path, project_root=root)
    run = json.loads(paths[0].read_text(encoding="utf-8"))
    assert run["verification"]["passed"] is True and run["final_build"]["success"] is False
    assert run["final_materialization"]["success"] is True
    assert run["project_quality"]["build"] == report["records"][0]["build"]
    assert next(check for check in run["checks"] if check["name"] == "target_materialization_success")["passed"] is True
    assert all(check["name"] not in {"final_build_success", "target_model_build_success"} for check in run["checks"])
    assert any(check["passed"] is False and check["required"] is False for check in run["extra_quality"])
    assert "附加 dbt build 未通过" in run["final_answer"] and "附加 dbt build 未通过" in run["events"][0]["content"]
    assert "177 original null IDs" in str(run["events"])


@pytest.mark.parametrize("failure", ["dependency", "pytest", "missing_dependency", "quality", "missing_policy", "build_exception"])
def test_upstream_exporter_rejects_missing_gates_or_conflicting_evidence(acceptance, failure):
    root, path, report = acceptance
    apply_upstream_policy(report)
    row = report["records"][0]
    if failure == "dependency":
        attach_dependency(row, success=False)
        row["verification"]["target_materialization_success"] = False
    elif failure == "pytest":
        row["raw_verifier"].update({"returncode": 1, "reward": 0.0, "pytest_returncode": 1, "stdout": "1 failed in 0.1s"})
        write_json(Path(row["artifacts"]["verifier_report"]), row["raw_verifier"])
    elif failure == "missing_dependency":
        row.pop("dependency_build")
    elif failure == "quality":
        row["project_quality"]["build"]["success"] = True
    elif failure == "build_exception":
        row["errors"] = [{"stage": "build", "type": "OSError", "error": "artifact read failure"}]
    else:
        report["protocol"].pop("acceptance_policy")
        report["protocol"].pop("build_required")
    write_json(path, report)
    with pytest.raises(ValueError):
        recordings.export_report(path, project_root=root)
    assert not (root / "examples/recorded_runs").exists()


def mark_preparation_unexecuted(row):
    case = Path(row["case_directory"])
    (case / "native-case.json").unlink()
    (case / "project" / row["model_path"]).unlink()
    row.pop("preparation")
    row.pop("applied_patch_sha256")
    row.pop("raw_verifier")
    row["artifacts"].pop("verifier_report")
    row["build"] = {"success": False}
    write_json(Path(row["artifacts"]["build_report"]), row["build"])
    row["verification"] = {"passed": False}
    row["status"] = "failed"
    row["errors"] = [{"stage": "prepare/apply", "type": "RuntimeError", "error": "deps network reset"},
                     {"stage": "evaluate", "type": "FileNotFoundError", "error": "native-case.json missing"}]
    write_json(case / "preparation/deps.json", {"returncode": 2, "stdout": "ConnectionResetError"})


def test_preparation_failure_is_exported_without_fabricating_application_or_pytest(acceptance):
    root, path, report = acceptance
    row = report["records"][0]
    mark_preparation_unexecuted(row)
    report["summary"]["accepted"] = 1
    write_json(path, report)
    paths, audit = recordings.export_report(path, project_root=root)
    run = json.loads(paths[0].read_text(encoding="utf-8"))
    assert audit["records"][0]["accepted"] is False and audit["records"][0]["unexecuted"] is True
    assert len(paths) == 2 and run["verification"]["passed"] is False
    assert run["verification"]["original_tests_executed"] is False
    assert run["diff"] == "" and run["status"] == "failed" and run["metrics"]["model_calls"] == 0
    assert all(field not in run for field in ("applied_sql", "applied_patch_sha256", "raw_verifier", "final_build"))
    assert run["checks"] == [{"name": "prepare_success", "passed": False, "expected": True, "actual": False}]
    assert "未执行" in run["final_answer"] and run["preparation_failure"]["logs"]
    saved_report = json.loads(path.read_text(encoding="utf-8"))
    assert saved_report["planned_tasks"] == 2 and saved_report["summary"]["accepted"] == 1


@pytest.mark.parametrize("corruption", ["accepted", "invented_pytest", "successful_build", "fake_applied_sha", "source_hash"])
def test_unexecuted_failure_cannot_claim_acceptance_or_fabricated_execution(acceptance, corruption):
    root, path, report = acceptance
    row = report["records"][0]
    mark_preparation_unexecuted(row)
    report["summary"]["accepted"] = 1
    if corruption == "accepted":
        row["verification"]["passed"] = True
        report["summary"]["accepted"] = 2
    elif corruption == "invented_pytest":
        row["raw_verifier"] = {"reward": 1, "returncode": 0, "stdout": "1 passed in 0.1s"}
    elif corruption == "successful_build":
        row["build"]["success"] = True
        write_json(Path(row["artifacts"]["build_report"]), row["build"])
    elif corruption == "fake_applied_sha":
        row["applied_patch_sha256"] = row["patch_sha256"]
    else:
        Path(row["patch_source"]).write_bytes(b"CHANGED PATCH")
    write_json(path, report)
    with pytest.raises((ValueError, FileNotFoundError, KeyError)):
        recordings.export_report(path, project_root=root)
    assert not (root / "examples/recorded_runs").exists()


@pytest.mark.parametrize("source_kind", ["root_overlay", "data_overlay", "base_original"])
def test_fix_model_uses_explicit_real_overlay_or_unchanged_base_for_original_diff(acceptance, source_kind):
    root, path, report = acceptance
    row = report["records"][1]
    snapshot = Path(report["input_snapshot"]["snapshot_lock"]).parent
    basename = Path(row["model_path"]).name
    if source_kind == "base_original":
        overlay = None
        original = snapshot / "base-image/dbt_models_duckdb" / row["model_path"]
    else:
        overlay = ("environment/" if source_kind == "root_overlay" else "environment/data/") + basename
        original = snapshot / "tasks" / row["task_id"] / overlay
    initial = ("select 'actual_" + source_kind + "' as original\n").encode()
    write_bytes(original, initial)
    row["preparation"]["bug_overlay"] = overlay
    write_json(Path(row["case_directory"]) / "native-case.json", row["preparation"])
    lock_path = Path(report["input_snapshot"]["snapshot_lock"])
    lock = json.loads(lock_path.read_text())
    old_inputs = row["input_files"]
    instruction_input = next(item for item in old_inputs if item["path"].endswith("instruction.md"))
    lock["files"] = [item for item in lock["files"] if item not in old_inputs] + [instruction_input]
    original_entry = {"path": original.relative_to(snapshot).as_posix(), "sha256": recordings._sha256(original), "bytes": original.stat().st_size}
    lock["files"].append(original_entry)
    row["input_files"] = [item for item in lock["files"] if item["path"].startswith("tasks/" + row["task_id"] + "/")]
    write_json(lock_path, lock)
    report["input_snapshot"]["snapshot_lock_sha256"] = recordings._sha256(lock_path)
    write_json(path, report)
    paths, _ = recordings.export_report(path, project_root=root)
    run = json.loads(paths[1].read_text(encoding="utf-8"))
    assert "-select 'actual_" + source_kind + "' as original" in run["diff"]
    assert original.relative_to(root).as_posix() in run["source_artifacts"]["original_buggy_sql"].replace("\\", "/")


def test_public_copy_with_workspace_paths_redacted_still_binds_original_artifacts(acceptance):
    root, path, report = acceptance
    row = report["records"][0]
    row["raw_verifier"]["stdout"] += "\nworkspace: " + str(root)
    write_json(Path(row["artifacts"]["verifier_report"]), row["raw_verifier"])
    write_json(path, recordings._clean(report, {str(root)}))
    paths, audit = recordings.export_report(path, project_root=root)
    assert len(paths) == 2 and audit["passed"]
    assert "$PROJECT" in paths[0].read_text(encoding="utf-8")


@pytest.mark.parametrize("source", ["patch", "applied_sql", "verifier", "input"])
def test_source_byte_or_saved_artifact_tampering_refuses_export(acceptance, source):
    root, path, report = acceptance
    row = report["records"][0]
    targets = {"patch": Path(row["patch_source"]),
               "applied_sql": Path(row["case_directory"]) / "project" / row["model_path"],
               "verifier": Path(row["artifacts"]["verifier_report"]),
               "input": Path(report["input_snapshot"]["snapshot_lock"]).parent / row["input_files"][0]["path"]}
    targets[source].write_bytes(b"CHANGED SOURCE")
    with pytest.raises((ValueError, json.JSONDecodeError)):
        recordings.export_report(path, project_root=root)
    assert not (root / "examples/recorded_runs").exists()


def test_running_report_is_rejected_and_existing_recordings_are_preserved(acceptance):
    root, path, report = acceptance
    report["status"] = "running"
    write_json(path, report)
    with pytest.raises(ValueError, match="completed"):
        recordings.export_report(path, project_root=root)
    report["status"] = "completed"
    write_json(path, report)
    paths, _ = recordings.export_report(path, project_root=root)
    original = [p.read_bytes() for p in paths]
    again, _ = recordings.export_report(path, project_root=root)
    assert again == paths and [p.read_bytes() for p in paths] == original
    paths[0].write_bytes(b"HISTORICAL RECORDING")
    with pytest.raises(ValueError, match="refusing overwrite"):
        recordings.export_report(path, project_root=root)
    assert paths[0].read_bytes() == b"HISTORICAL RECORDING" and paths[1].read_bytes() == original[1]
