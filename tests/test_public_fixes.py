from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("public_fixes", Path(__file__).resolve().parents[1] / "scripts/verify_public_fixes.py")
fixes = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(fixes)


def test_expanded_tasks_are_explicit_and_keep_original_acceptance_defaults():
    assert fixes.DEFAULT_TASKS == ("dbt-fix-product-metrics", "dbt-fix-refund-reconciliation",
                                   "dbt-fix-division-by-zero", "dbt-fix-inventory-model")
    # The ninth supported task is a fresh blind trial, not a reviewed patch.
    assert len(fixes.CASE_NAMES) == 8
    assert set(fixes.CASE_NAMES) < set(fixes.adapter.PUBLIC_TASK_MODELS)
    assert "dbt-carrier-delivery-performance" not in fixes.CASE_NAMES
    assert {task: fixes.CASE_NAMES[task] for task in (
        "dbt-fix-timezone-sales", "dbt-fix-daily-revenue", "dbt-exchange-rate-settlement-date", "cohort-retention-matrix"
    )} == {"dbt-fix-timezone-sales": "timezone", "dbt-fix-daily-revenue": "daily",
            "dbt-exchange-rate-settlement-date": "fx", "cohort-retention-matrix": "cohort"}


@pytest.fixture
def offline_acceptance(tmp_path, monkeypatch):
    patches, snapshot = tmp_path / "patches", tmp_path / "snapshot"
    patches.mkdir()
    database = snapshot / "base-image/database/retail.duckdb"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"original-input-database")
    lock = {"repository": fixes.adapter.REPOSITORY, "commit": fixes.adapter.PINNED_COMMIT,
            "tasks": list(fixes.DEFAULT_TASKS), "database": {"bytes": database.stat().st_size, "sha256": hashlib.sha256(database.read_bytes()).hexdigest()}, "files": []}
    (snapshot / "snapshot-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    for task in fixes.DEFAULT_TASKS:
        (patches / (task + ".sql")).write_bytes(b"-- operator_reviewed\nselect 42 as reviewed_result\n")
    state = {"events": [], "reject": None, "targets": [], "dependency_fail": None, "dependency_target_fail": None,
             "build_fail": None, "build_raise": None, "requires_new_ref": None, "preregistered": []}

    def prepare(source, case, task, **kwargs):
        state.setdefault("prepare_options", []).append(kwargs)
        state["events"].append((task, "prepare"))
        state["preregistered"].append(json.loads((tmp_path / "acceptance/report.json").read_text(encoding="utf-8")))
        (case / "project/models").mkdir(parents=True)
        (case / "project/models/unrelated.sql").write_text("KEEP ME", encoding="utf-8")
        (case / "task.txt").write_text(task, encoding="utf-8")
        metadata = {"task_id": task, "initialized": True}
        if kwargs.get("duckdb_timezone") is not None:
            metadata["runtime_settings"] = {"duckdb_timezone": kwargs["duckdb_timezone"]}
        return metadata

    class FakeWorkspace:
        def __init__(self, root, project_dir, database_path, *, duckdb_timezone=None):
            self.case = root
            state.setdefault("workspace_timezones", []).append(duckdb_timezone)
        def run_dbt(self, command, select):
            task = (self.case / "task.txt").read_text(encoding="utf-8")
            model = Path(fixes.adapter.PUBLIC_TASK_MODELS[task]).stem
            assert (command, select) in (("run", "+" + model), ("build", model))
            state["events"].append((task, "dependencies" if command == "run" else "build"))
            target = self.case / "project" / fixes.adapter.PUBLIC_TASK_MODELS[task]
            assert target.read_bytes() == (patches / (task + ".sql")).read_bytes()
            assert (self.case / "project/models/unrelated.sql").read_text(encoding="utf-8") == "KEEP ME"
            if command == "run":
                # A newly introduced ref is materialized only after the patch is applied.
                if task == state["requires_new_ref"]:
                    assert b"ref('new_dependency')" in target.read_bytes()
                    (self.case / "new_dependency.ready").write_text("materialized", encoding="utf-8")
                return {"success": task != state["dependency_fail"], "target_model_success": task != state["dependency_target_fail"],
                        "stdout": "DEPENDENCY RUN STDOUT", "stderr": ""}
            if task == state["requires_new_ref"]:
                assert (self.case / "new_dependency.ready").is_file()
            if task == state["build_raise"]:
                raise OSError("manifest or artifact could not be read")
            state["targets"].append(target)
            return {"success": task != state["build_fail"], "stdout": "ORIGINAL BUILD STDOUT", "stderr": ""}

    def verify_build(build, project, model):
        return {**build, "target_model_success": build.get("target_model_success", True), "target_model": Path(model).stem}

    def evaluate(case, evaluator_root):
        task = (case / "task.txt").read_text(encoding="utf-8")
        state["events"].append((task, "pytest"))
        assert not evaluator_root.is_relative_to(case)
        rejected = task == state["reject"]
        raw = {"returncode": int(rejected), "reward": 0.0 if rejected else 1.0,
               "stdout": "1 failed in 0.1s" if rejected else "1 passed in 0.1s",
               "components_passed": [] if rejected else ["component_1_model_compiles"],
               "components_failed": ["component_1_model_compiles"] if rejected else [], "grading_protocol": "component_reward_json"}
        if task == "dbt-fix-product-metrics":
            raw.update({"grading_protocol": "pytest_exit_status", "pytest_returncode": int(rejected),
                        "pytest_counts": {"passed": 0 if rejected else 1, "failed": int(rejected), "errors": 0, "skipped": 0},
                        "components_passed": [], "components_failed": []})
        p = evaluator_root / task / "original-verifier-report.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(raw), encoding="utf-8")
        return {"report": str(p)}

    monkeypatch.setattr(fixes.adapter, "prepare_native_case", prepare)
    monkeypatch.setattr(fixes.adapter, "verify_target_build", verify_build)
    monkeypatch.setattr(fixes.adapter, "evaluate_native_case", evaluate)
    monkeypatch.setattr(fixes, "Workspace", FakeWorkspace)
    return patches, snapshot, tmp_path / "fresh-cases", tmp_path / "acceptance/report.json", state


def test_explicit_utc_configuration_is_predeclared_and_forwarded(offline_acceptance):
    patches, snapshot, cases, output, state = offline_acceptance
    task = fixes.DEFAULT_TASKS[0]
    report = fixes.verify_fixes(patches, cases, output, (task,), snapshot=snapshot, duckdb_timezone="UTC")
    assert state["prepare_options"] == [{"duckdb_timezone": "UTC"}]
    assert state["preregistered"][0]["protocol"]["runtime_settings"] == {"duckdb_timezone": "UTC"}
    assert report["protocol"]["runtime_settings"] == {"duckdb_timezone": "UTC"}
    assert state["workspace_timezones"] == ["UTC", "UTC"]
    assert report["summary"]["accepted"] == 1


def test_verified_packages_cache_is_predeclared_and_forwarded(offline_acceptance, tmp_path):
    patches, snapshot, cases, output, state = offline_acceptance
    cache = tmp_path / "verified-cache"
    cache.mkdir()
    (cache / "receipt.json").write_bytes(b'{"resolved_version":"1.3.3"}\n')
    report = fixes.verify_fixes(patches, cases, output, (fixes.DEFAULT_TASKS[0],), snapshot=snapshot, packages_cache=cache)
    assert state["prepare_options"] == [{"packages_cache": cache.resolve()}]
    assert state["preregistered"][0]["protocol"]["packages_cache"] == str(cache.resolve())
    assert report["protocol"]["packages_cache_receipt_sha256"] == hashlib.sha256((cache / "receipt.json").read_bytes()).hexdigest()


def test_all_reviewed_patches_use_original_inputs_and_original_tests_without_agent_metrics(offline_acceptance):
    patches, snapshot, cases, output, state = offline_acceptance
    report = fixes.verify_fixes(patches, cases, output, snapshot=snapshot)
    assert state["events"] == [(task, phase) for task in fixes.DEFAULT_TASKS for phase in ("prepare", "dependencies", "build", "pytest")]
    assert report["type"] == "reviewed_patch_acceptance" and report["patch_origin"] == "operator_reviewed"
    assert report["zero_api_calls"] is True and report["summary"]["accepted"] == report["planned_tasks"] == 4
    assert report["status"] == "completed" and output.is_file() and output.with_suffix(".md").is_file()
    assert "model_calls" not in output.read_text(encoding="utf-8") and "completion_tokens" not in output.read_text(encoding="utf-8")
    assert state["preregistered"][0]["records"] == []
    assert state["preregistered"][0]["protocol"]["acceptance_policy"] == "dbt_build"
    assert state["preregistered"][0]["protocol"]["task_ids"] == list(fixes.DEFAULT_TASKS)
    for row in report["records"]:
        assert row["patch_sha256"] == row["applied_patch_sha256"]
        assert row["build"]["stdout"] == "ORIGINAL BUILD STDOUT" and row["raw_verifier"]["reward"] == 1
        assert Path(row["artifacts"]["verifier_report"]).is_file()
        assert row["dependency_build"]["success"] is True
        assert Path(row["artifacts"]["dependency_build_report"]).is_file()


def test_subset_has_one_task_denominator_and_failure_is_preserved(offline_acceptance):
    patches, snapshot, cases, output, state = offline_acceptance
    state["reject"] = "dbt-fix-product-metrics"
    report = fixes.verify_fixes(patches, cases, output, (state["reject"],), snapshot=snapshot)
    assert report["planned_tasks"] == 1 and report["summary"]["accepted"] == 0
    assert report["records"][0]["verification"]["passed"] is False
    assert len(state["events"]) == 4


def test_candidate_new_ref_is_materialized_after_patch_before_target_build(offline_acceptance):
    patches, snapshot, cases, output, state = offline_acceptance
    task = fixes.DEFAULT_TASKS[0]
    state["requires_new_ref"] = task
    (patches / (task + ".sql")).write_bytes(b"-- operator_reviewed\nselect * from {{ ref('new_dependency') }}\n")
    report = fixes.verify_fixes(patches, cases, output, (task,), snapshot=snapshot)
    assert report["summary"]["accepted"] == 1
    assert state["events"] == [(task, phase) for phase in ("prepare", "dependencies", "build", "pytest")]


def test_failed_dependencies_cannot_pass_using_preexisting_target_and_passing_pytest(offline_acceptance):
    patches, snapshot, cases, output, state = offline_acceptance
    task = fixes.DEFAULT_TASKS[0]
    state["dependency_fail"] = task
    report = fixes.verify_fixes(patches, cases, output, (task,), snapshot=snapshot)
    row = report["records"][0]
    assert row["build"]["success"] is True and row["verification"]["original_tests_passed"] is True
    assert row["dependency_build"]["success"] is False
    assert row["verification"]["passed"] is False and report["summary"]["accepted"] == 0


@pytest.mark.parametrize("policy", [None, "dbt_build"])
def test_build_failure_remains_required_by_default_or_explicit_strict_policy(offline_acceptance, policy):
    patches, snapshot, cases, output, state = offline_acceptance
    task = fixes.DEFAULT_TASKS[0]
    state["build_fail"] = task
    kwargs = {} if policy is None else {"acceptance_policy": policy}
    report = fixes.verify_fixes(patches, cases, output, (task,), snapshot=snapshot, **kwargs)
    row = report["records"][0]
    assert row["verification"]["build_required"] is True and row["verification"]["passed"] is False
    assert row["verification"]["target_materialization_success"] is True


def test_explicit_upstream_policy_preserves_failed_build_as_nonrequired_project_quality(offline_acceptance):
    patches, snapshot, cases, output, state = offline_acceptance
    task = fixes.DEFAULT_TASKS[0]
    state["build_fail"] = task
    report = fixes.verify_fixes(patches, cases, output, (task,), snapshot=snapshot, acceptance_policy="upstream_harness")
    row = report["records"][0]
    assert row["verification"]["passed"] is True and report["summary"]["accepted"] == 1
    assert row["verification"]["build_required"] is False and row["verification"]["target_materialization_success"] is True
    assert row["build"]["success"] is False and row["project_quality"]["build"] == row["build"]
    assert json.loads(Path(row["artifacts"]["build_report"]).read_text())["success"] is False
    assert state["preregistered"][0]["protocol"]["acceptance_policy"] == "upstream_harness"
    assert state["preregistered"][0]["records"] == []


@pytest.mark.parametrize("failure", ["dependency_fail", "dependency_target_fail", "reject"])
def test_upstream_policy_still_requires_real_candidate_materialization_and_original_pytest(offline_acceptance, failure):
    patches, snapshot, cases, output, state = offline_acceptance
    task = fixes.DEFAULT_TASKS[0]
    state[failure] = task
    report = fixes.verify_fixes(patches, cases, output, (task,), snapshot=snapshot, acceptance_policy="upstream_harness")
    row = report["records"][0]
    assert row["verification"]["passed"] is False and report["summary"]["accepted"] == 0


def test_upstream_policy_never_exempts_python_or_io_build_exceptions(offline_acceptance):
    patches, snapshot, cases, output, state = offline_acceptance
    task = fixes.DEFAULT_TASKS[0]
    state["build_raise"] = task
    report = fixes.verify_fixes(patches, cases, output, (task,), snapshot=snapshot, acceptance_policy="upstream_harness")
    row = report["records"][0]
    assert row["verification"]["target_materialization_success"] is True
    assert row["verification"]["original_tests_passed"] is True
    assert row["verification"]["passed"] is False and report["summary"]["accepted"] == 0
    assert row["status"] == "failed" and row["errors"][0]["stage"] == "build"
    assert row["errors"][0]["type"] == "OSError"
    assert state["events"][-1] == (task, "pytest")


def test_unknown_acceptance_policy_is_rejected_before_preparation(offline_acceptance):
    patches, snapshot, cases, output, state = offline_acceptance
    with pytest.raises(ValueError, match="policy"):
        fixes.verify_fixes(patches, cases, output, snapshot=snapshot, acceptance_policy="skip_all")
    assert not state["events"] and not output.exists()


def test_existing_case_root_or_report_is_never_overwritten(offline_acceptance):
    patches, snapshot, cases, output, state = offline_acceptance
    cases.mkdir()
    sentinel = cases / "history.txt"
    sentinel.write_text("HISTORY", encoding="utf-8")
    with pytest.raises(ValueError, match="new"):
        fixes.verify_fixes(patches, cases, output, snapshot=snapshot)
    assert sentinel.read_text(encoding="utf-8") == "HISTORY" and not state["events"]


def test_unmarked_patch_is_rejected_before_any_preparation(offline_acceptance):
    patches, snapshot, cases, output, state = offline_acceptance
    (patches / (fixes.DEFAULT_TASKS[0] + ".sql")).write_text("select 1", encoding="utf-8")
    with pytest.raises(ValueError, match="operator_reviewed"):
        fixes.verify_fixes(patches, cases, output, snapshot=snapshot)
    assert not cases.exists() and not output.exists() and not state["events"]


def test_snapshot_hash_mismatch_is_rejected_without_build_or_pytest(offline_acceptance):
    patches, snapshot, cases, output, state = offline_acceptance
    (snapshot / "base-image/database/retail.duckdb").write_bytes(b"modified-inputs")
    with pytest.raises(ValueError, match="database"):
        fixes.verify_fixes(patches, cases, output, snapshot=snapshot)
    assert not cases.exists() and not state["events"]
