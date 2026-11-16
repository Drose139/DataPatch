from __future__ import annotations

import importlib.util
import hashlib
import io
import json
from pathlib import Path

import pytest


def module_from_path(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


fetch = module_from_path("benchmark_fetch", "scripts/fetch_public_benchmark.py")
adapter = module_from_path("benchmark_adapter", "integrations/harbor_agent.py")


def test_fetch_allowlist_excludes_answers_and_other_tasks():
    tasks = ("dbt-fix-refund-reconciliation",)
    assert fetch.selected_path("base-image/dbt_models_duckdb/tests/generic/test_not_null.sql", tasks)
    assert fetch.selected_path("tasks/dbt-fix-refund-reconciliation/environment/data/rpt_return_reconciliation.sql", tasks)
    for path in (
        "tasks/dbt-fix-refund-reconciliation/solution/solve.sh",
        "tasks/dbt-fix-refund-reconciliation/tests/test_outputs.py",
        "tasks/another-task/instruction.md",
        "base-image/dbt_models_duckdb/../../solution/solve.sh",
        "tasks/dbt-fix-refund-reconciliation/environment/data/unlisted.sql",
    ):
        assert not fetch.selected_path(path, tasks)


def test_root_overlays_are_exact_allowlisted_inputs():
    tasks = ("dbt-fix-timezone-sales", "dbt-fix-daily-revenue", "dbt-exchange-rate-settlement-date")
    for task in tasks[:2]:
        assert fetch.selected_path(f"tasks/{task}/{fetch.BUG_MODEL_INPUTS[task]}", tasks)
    for path in (
        "tasks/dbt-fix-timezone-sales/environment/solution.sql",
        "tasks/dbt-fix-daily-revenue/environment/data/unlisted.sql",
        "tasks/dbt-exchange-rate-settlement-date/environment/fact_revenue.sql",
        "tasks/dbt-fix-timezone-sales/tests/test_outputs.py",
    ):
        assert not fetch.selected_path(path, tasks)
    assert fetch.BUG_MODEL_INPUTS == adapter.BUG_MODEL_INPUTS


@pytest.mark.parametrize("task_id", ["dbt-fix-refund-reconciliation", "dbt-fix-inventory-model", "dbt-fix-timezone-sales", "dbt-fix-daily-revenue", "dbt-carrier-delivery-performance"])
def test_prepare_overlays_bug_without_copying_private_material(tmp_path, task_id):
    snapshot = tmp_path / "snapshot"
    target = adapter.PUBLIC_TASK_MODELS[task_id]
    original = snapshot / "base-image/dbt_models_duckdb" / target
    original.parent.mkdir(parents=True)
    original.write_text("select 'base' as state", encoding="utf-8")
    (snapshot / "base-image/database").mkdir()
    (snapshot / "base-image/database/retail.duckdb").write_bytes(b"test-database")
    task = snapshot / "tasks" / task_id
    overlay = task / adapter.BUG_MODEL_INPUTS[task_id]
    overlay.parent.mkdir(parents=True)
    overlay.write_text("select 'bug' as state", encoding="utf-8")
    (task / "instruction.md").write_text("Edit /app/dbt_models_duckdb/" + target, encoding="utf-8")
    (task / "solution").mkdir()
    (task / "solution/solve.sh").write_text("secret-reference", encoding="utf-8")
    (snapshot / "snapshot-lock.json").write_text(json.dumps({"commit": adapter.PINNED_COMMIT, "tasks": [task_id], "database": {"bytes": 13}}), encoding="utf-8")
    case = tmp_path / "case"
    metadata = adapter.prepare_native_case(snapshot, case, task_id, initialize=False)
    assert metadata["official_harbor_result"] is False
    assert metadata["bug_overlay"] == adapter.BUG_MODEL_INPUTS[task_id]
    assert (case / "project" / target).read_text(encoding="utf-8") == "select 'bug' as state"
    assert not list(case.rglob("solve.sh"))
    assert "/app/dbt_models_duckdb" not in (case / "instruction.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        adapter.prepare_native_case(snapshot, case, task_id, initialize=False)


def test_no_overlay_task_preserves_original_model(tmp_path):
    snapshot = tmp_path / "snapshot"
    task_id = "dbt-exchange-rate-settlement-date"
    target = adapter.PUBLIC_TASK_MODELS[task_id]
    original = snapshot / "base-image/dbt_models_duckdb" / target
    original.parent.mkdir(parents=True)
    original.write_bytes(b"select 42 as existing_revenue\n")
    (snapshot / "base-image/database").mkdir()
    (snapshot / "base-image/database/retail.duckdb").write_bytes(b"test-database")
    task = snapshot / "tasks" / task_id
    task.mkdir(parents=True)
    (task / "instruction.md").write_text("Fix settlement date in existing fact_revenue", encoding="utf-8")
    (snapshot / "snapshot-lock.json").write_text(json.dumps({"commit": adapter.PINNED_COMMIT, "tasks": [task_id], "database": {"bytes": 13}}), encoding="utf-8")
    case = tmp_path / "case"
    metadata = adapter.prepare_native_case(snapshot, case, task_id, initialize=False)
    assert metadata["bug_overlay"] is None and metadata["task_type"] == "fix-model"
    assert (case / "project" / target).read_bytes() == original.read_bytes()
    assert metadata["initialization_selectors"] == ["fact_revenue"]


@pytest.mark.parametrize("task_id", ["dbt-fix-product-metrics", "cohort-retention-matrix"])
@pytest.mark.parametrize("duckdb_timezone", [None, "UTC"])
def test_new_model_task_initializes_declared_inputs_without_creating_answer(tmp_path, monkeypatch, task_id, duckdb_timezone):
    snapshot = tmp_path / "snapshot"
    project = snapshot / "base-image/dbt_models_duckdb"
    (project / "models/staging").mkdir(parents=True)
    for name in adapter.CREATE_MODEL_ANCESTORS[task_id]:
        (project / "models/staging" / (name + ".sql")).write_text("select 1 as id", encoding="utf-8")
    (snapshot / "base-image/database").mkdir()
    (snapshot / "base-image/database/retail.duckdb").write_bytes(b"test-database")
    task = snapshot / "tasks" / task_id
    task.mkdir(parents=True)
    instruction = "Create " + adapter.PUBLIC_TASK_MODELS[task_id]
    if task_id == "cohort-retention-matrix":
        instruction += " in schema main_marketing_analytics using config(schema='marketing_analytics')"
    (task / "instruction.md").write_text(instruction, encoding="utf-8")
    (snapshot / "snapshot-lock.json").write_text(json.dumps({"commit": adapter.PINNED_COMMIT, "tasks": [task_id], "database": {"bytes": 13}}), encoding="utf-8")
    commands = []
    monkeypatch.setattr(adapter, "run_recorded", lambda command, **kwargs: commands.append(command))
    monkeypatch.setattr(adapter, "dbt_executable", lambda: "dbt")
    case = tmp_path / "case"
    meta = adapter.prepare_native_case(snapshot, case, task_id, duckdb_timezone=duckdb_timezone)
    assert meta["task_type"] == "create-model" and meta["initialized"]
    assert not (case / "project" / adapter.PUBLIC_TASK_MODELS[task_id]).exists()
    assert commands[-1][commands[-1].index("--select") + 1:] == ["+" + name for name in adapter.CREATE_MODEL_ANCESTORS[task_id]]
    assert instruction in (case / "instruction.md").read_text(encoding="utf-8")
    assert "schema: main\n" in (case / "project/profiles.yml").read_text(encoding="utf-8")
    profile = (case / "project/profiles.yml").read_text(encoding="utf-8")
    if duckdb_timezone is None:
        assert "TimeZone" not in profile and "runtime_settings" not in meta
    else:
        assert "settings:\n        TimeZone: 'UTC'" in profile
        assert meta["runtime_settings"] == {"duckdb_timezone": "UTC"}
        assert meta["runtime"]["duckdb_timezone"] == "UTC"


@pytest.mark.parametrize("duckdb_timezone", [None, "UTC"])
def test_verifier_utc_launcher_is_explicit_and_default_invocation_unchanged(tmp_path, monkeypatch, duckdb_timezone):
    from types import SimpleNamespace
    case = tmp_path / "case"
    case.mkdir()
    meta = {"task_id": "dbt-fix-product-metrics", "upstream_commit": adapter.PINNED_COMMIT}
    if duckdb_timezone is not None:
        meta["runtime_settings"] = {"duckdb_timezone": duckdb_timezone}
        meta["runtime_adaptations"] = {"packages_cache": {"receipt_sha256": "a" * 64, "resolved_version": "1.3.3"}}
    (case / "native-case.json").write_text(json.dumps(meta), encoding="utf-8")
    source = b"def test_business_assertion():\n    assert 2 + 2 == 4\n"
    monkeypatch.setattr(adapter.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(source))
    commands = []
    def execute(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="1 passed in 0.01s\n", stderr="")
    monkeypatch.setattr(adapter.subprocess, "run", execute)
    result = adapter.evaluate_native_case(case, tmp_path / "evaluators")
    raw = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
    assert raw["path_translation_only"] is True
    assert raw["original_sha256"] == raw["adapted_sha256"] == hashlib.sha256(source).hexdigest()
    assert Path(commands[0][-1]).read_bytes() == source
    if duckdb_timezone is None:
        assert commands[0][1:3] == ["-m", "pytest"]
        assert "runtime_launcher" not in raw and "runtime_settings" not in raw
    else:
        assert commands[0][2:4] == ["--duckdb-timezone", "UTC"]
        assert raw["runtime_settings"] == {"duckdb_timezone": "UTC"}
        launcher = raw["runtime_launcher"]
        assert Path(commands[0][1]) == Path(launcher["archive_path"])
        assert hashlib.sha256(Path(launcher["archive_path"]).read_bytes()).hexdigest() == launcher["sha256"]
        assert Path(launcher["archive_path"]).read_bytes() == Path(launcher["source_path"]).read_bytes()
        assert raw["runtime_adaptations"] == meta["runtime_adaptations"]


def test_fetch_rejects_empty_duplicate_or_unknown_subset_before_network(tmp_path):
    for tasks in ((), (fetch.DEFAULT_TASKS[0],) * 2, ("unknown-task",)):
        with pytest.raises(ValueError, match="subset"):
            fetch.fetch_snapshot(tmp_path, tasks)
    assert set(fetch.SUPPORTED_TASKS) == set(adapter.PUBLIC_TASK_MODELS)
    assert fetch.DEFAULT_TASKS == adapter.LEGACY_TASKS
    assert len(adapter.PUBLIC_TASK_MODELS) == 9
    assert adapter.EXPLICIT_GRADING_TASKS == {"dbt-carrier-delivery-performance"}
    assert set(adapter.PUBLIC_TASK_MODELS) - set(adapter.LEGACY_TASKS) - {"dbt-fix-inventory-model"} <= adapter.PYTEST_EXIT_STATUS_TASKS | adapter.EXPLICIT_GRADING_TASKS


def test_final_verifier_must_live_outside_agent_case(tmp_path):
    case = tmp_path / "case"
    case.mkdir()
    with pytest.raises(ValueError, match="outside"):
        adapter.evaluate_native_case(case, case / "hidden-tests")


def test_evaluator_really_invokes_pytest_and_preserves_binary_failure(tmp_path, monkeypatch):
    case = tmp_path / "case"
    case.mkdir()
    (case / "native-case.json").write_text(json.dumps({"task_id": "dbt-fix-refund-reconciliation", "upstream_commit": adapter.PINNED_COMMIT}), encoding="utf-8")
    # Like upstream, importing/running this module directly executes no test.
    source = b'''from pathlib import Path
def test_solution():
    print("PASS: component_1_model_compiles")
    print("FAIL: component_2_business_rule: counterexample")
    output = Path("/logs/verifier")
    output.mkdir(parents=True, exist_ok=True)
    (output / "reward.json").write_text('{"reward": 0.0}')
    assert False, "binary task failed despite a passing component"
'''
    monkeypatch.setattr(adapter.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(source))
    result = adapter.evaluate_native_case(case, tmp_path / "evaluators")
    assert result["returncode"] == 1
    assert result["reward"] == 0.0
    assert result["components_passed"] == result["components_failed"] == 1
    raw = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
    adapted_file = Path(result["report"]).parent / "test_outputs_case.py"
    assert hashlib.sha256(adapted_file.read_bytes()).hexdigest() == raw["adapted_sha256"]


def native_summary_inputs(tmp_path, task_id, case_name):
    case = tmp_path / case_name
    case.mkdir()
    (case / "native-case.json").write_text(json.dumps({"task_id": task_id, "base_build": "selected inputs", "runtime": {"platform": "test"}}), encoding="utf-8")
    results = tmp_path / "agents"
    results.mkdir(exist_ok=True)
    (results / f"{case_name}-verified.json").write_text(json.dumps({"model": "example-model", "max_steps": 24, "budget_usd": 0.6,
        "generation_settings": {"thinking_enabled": True, "reasoning_effort": "high", "max_output_tokens": 16384},
        "observed_model_versions": ["example-model-version"],
        "result": {"stop_reason": "model_finished", "metrics": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}}), encoding="utf-8")
    evaluators = tmp_path / "evaluators"
    directory = evaluators / task_id
    directory.mkdir(parents=True, exist_ok=True)
    verifier = {"returncode": 0, "reward": 1.0, "components_passed": ["component_1_model_compiles"], "components_failed": [],
                "stdout": "PASS: component_1_model_compiles\n1 passed in 0.10s\n"}
    (directory / f"{case_name}-evaluation.json").write_text(json.dumps(verifier), encoding="utf-8")
    return case, results, evaluators


def test_expanded_adapter_keeps_default_historical_report_at_two_tasks(tmp_path):
    output = tmp_path / "report.json"
    for i, task in enumerate(adapter.LEGACY_TASKS):
        adapter.render_public_summary(*native_summary_inputs(tmp_path, task, f"case-{i}"), output)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["planned_trials"] == 2 and report["status"] == "completed"
    assert report["protocol"]["planned_task_ids"] == list(adapter.LEGACY_TASKS)
    assert report["records"][0]["observed_model_versions"] == ["example-model-version"]


def test_new_tasks_require_explicit_plan_and_plan_cannot_expand_later(tmp_path):
    task = "dbt-fix-inventory-model"
    inputs = native_summary_inputs(tmp_path, task, "inventory")
    output = tmp_path / "report.json"
    with pytest.raises(ValueError, match="outside"):
        adapter.render_public_summary(*inputs, output)
    adapter.render_public_summary(*inputs, output, planned_tasks=tuple(adapter.PUBLIC_TASK_MODELS))
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["planned_trials"] == len(adapter.PUBLIC_TASK_MODELS) and report["status"] == "running"
    with pytest.raises(ValueError, match="frozen"):
        adapter.render_public_summary(*inputs, output, planned_tasks=(task,))


def test_repeat_protocol_requires_distinct_numbers_and_completes_full_matrix(tmp_path):
    task = "dbt-fix-inventory-model"
    first = native_summary_inputs(tmp_path, task, "first")
    second = native_summary_inputs(tmp_path, task, "second")
    output = tmp_path / "repeat.json"
    adapter.render_public_summary(*first, output, planned_tasks=(task,), repeat=0, repeats=2)
    with pytest.raises(ValueError, match="Duplicate"):
        adapter.render_public_summary(*second, output, repeat=0)
    adapter.render_public_summary(*second, output, repeat=1)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "completed" and report["planned_trials"] == 2
    assert [row["repeat"] for row in report["records"]] == [0, 1]


def test_zero_exit_without_actual_pytest_summary_is_not_task_pass(tmp_path):
    inputs = native_summary_inputs(tmp_path, adapter.LEGACY_TASKS[0], "not-executed")
    verifier_path = inputs[2] / adapter.LEGACY_TASKS[0] / "not-executed-evaluation.json"
    verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
    verifier["stdout"] = "PASS: component_1_model_compiles\n"
    verifier_path.write_text(json.dumps(verifier), encoding="utf-8")
    output = tmp_path / "report.json"
    adapter.render_public_summary(*inputs, output)
    row = json.loads(output.read_text(encoding="utf-8"))["records"][0]
    assert row["verification"]["passed"] is False and row["status"] == "failed"


def test_actual_final_build_overrides_legacy_component_inference(tmp_path):
    inputs = native_summary_inputs(tmp_path, adapter.LEGACY_TASKS[0], "failed-build")
    path = inputs[1] / "failed-build-verified.json"
    agent = json.loads(path.read_text(encoding="utf-8"))
    agent["final_build"] = {"success": False, "stdout": "dbt build failed"}
    path.write_text(json.dumps(agent), encoding="utf-8")
    output = tmp_path / "report.json"
    adapter.render_public_summary(*inputs, output)
    row = json.loads(output.read_text(encoding="utf-8"))["records"][0]
    assert row["final_build"] == agent["final_build"]
    assert row["verification"]["passed"] is False


@pytest.mark.parametrize("returncode,passed,failed,errors,skipped,reward", [
    (0, 2, 0, 0, 0, 1.0), (0, 0, 0, 0, 0, 0.0), (1, 2, 0, 0, 0, 0.0),
    (0, 1, 1, 0, 0, 0.0), (0, 1, 0, 1, 0, 0.0), (0, 1, 0, 0, 1, 0.0),
])
def test_ordinary_pytest_binary_rule_requires_real_passes_without_failures_or_skips(returncode, passed, failed, errors, skipped, reward):
    counts = {"passed": passed, "failed": failed, "errors": errors, "skipped": skipped}
    assert adapter.pytest_exit_reward(returncode, counts) == reward


def test_pytest_counts_match_pinned_tail_count_extraction():
    assert adapter.pytest_counts("1 passed in 0.1s\n2 passed, 3 failed, 1 error, 4 skipped in 0.2s") == {"passed": 2, "failed": 3, "errors": 1, "skipped": 4}


@pytest.mark.parametrize("target_status,other_success,expected", [(None, False, False), (None, True, False), ("skipped", False, False), ("success", False, True)])
def test_build_requires_successful_requested_manifest_model(tmp_path, target_status, other_success, expected):
    project = tmp_path / "project"
    (project / "target").mkdir(parents=True)
    model_path = "models/marts/product/requested.sql"
    unique_id = "model.package_from_manifest.requested"
    (project / "target/manifest.json").write_text(json.dumps({"nodes": {unique_id: {"resource_type": "model", "name": "requested", "original_file_path": model_path}}}), encoding="utf-8")
    nodes = [] if target_status is None else [{"unique_id": unique_id, "status": target_status}]
    if other_success:
        nodes.append({"unique_id": "model.other_package.another", "status": "success"})
    (project / "target/run_results.json").write_text(json.dumps({"results": nodes}), encoding="utf-8")
    checked = adapter.verify_target_build({"success": True, "nodes": []}, project, model_path)
    assert checked["success"] is expected and checked["target_model_success"] is expected


def test_ordinary_pytest_verifier_uses_original_tests_and_records_shell_hash(tmp_path, monkeypatch):
    case = tmp_path / "ordinary-case"
    case.mkdir()
    task = "dbt-fix-product-metrics"
    (case / "native-case.json").write_text(json.dumps({"task_id": task, "upstream_commit": adapter.PINNED_COMMIT}), encoding="utf-8")
    test_source = b"def test_one():\n    assert True\n\ndef test_two():\n    assert False, 'business counterexample'\n"
    shell_source = b"pytest_output=$(pytest /tests/test_outputs.py -v 2>&1)\n# pinned shell scoring fixture\n"
    monkeypatch.setattr(adapter.urllib.request, "urlopen", lambda request, **kwargs: io.BytesIO(shell_source if request.full_url.endswith("test.sh") else test_source))
    result = adapter.evaluate_native_case(case, tmp_path / "evaluators")
    raw = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
    assert raw["grading_protocol"] == "pytest_exit_status" and raw["reward"] == 0.0 and raw["returncode"] == 1
    assert raw["pytest_counts"] == {"passed": 1, "failed": 1, "errors": 0, "skipped": 0}
    assert raw["scoring_source_sha256"] == hashlib.sha256(shell_source).hexdigest()
    assert Path(result["report"]).parent.joinpath("test.original.sh").read_bytes() == shell_source
    adapted_file = Path(result["report"]).parent / "test_outputs_ordinary_case.py"
    assert hashlib.sha256(adapted_file.read_bytes()).hexdigest() == raw["adapted_sha256"]


@pytest.mark.parametrize("protocol", [None, "guess-from-exit-code"])
def test_new_task_requires_explicit_grading_before_downloading_verifier(tmp_path, monkeypatch, protocol):
    case = tmp_path / "blind-case"
    case.mkdir()
    (case / "native-case.json").write_text(json.dumps({"task_id": "dbt-carrier-delivery-performance",
        "upstream_commit": adapter.PINNED_COMMIT}), encoding="utf-8")
    def no_network(*args, **kwargs):
        pytest.fail("Unspecified/unknown grading must be refused before downloading anything")
    monkeypatch.setattr(adapter.urllib.request, "urlopen", no_network)
    with pytest.raises(ValueError, match="explicit grading_protocol"):
        adapter.evaluate_native_case(case, tmp_path / "evaluators", grading_protocol=protocol)


def test_historical_task_grading_cannot_be_overridden(tmp_path):
    case = tmp_path / "old-case"
    case.mkdir()
    (case / "native-case.json").write_text(json.dumps({"task_id": adapter.LEGACY_TASKS[0],
        "upstream_commit": adapter.PINNED_COMMIT}), encoding="utf-8")
    with pytest.raises(ValueError, match="only supported"):
        adapter.evaluate_native_case(case, tmp_path / "evaluators", grading_protocol="pytest_exit_status")


@pytest.mark.parametrize("protocol", ["pytest_exit_status", "component_reward_json"])
def test_new_task_archives_harness_and_uses_explicit_protocol_without_guessing(tmp_path, monkeypatch, protocol):
    from types import SimpleNamespace
    case = tmp_path / "new-case"
    case.mkdir()
    task = "dbt-carrier-delivery-performance"
    (case / "native-case.json").write_text(json.dumps({"task_id": task,
        "upstream_commit": adapter.PINNED_COMMIT}), encoding="utf-8")
    # Synthetic fixtures only: never download/inspect the selected task here.
    test_source = b"def test_synthetic():\n    assert True\n"
    shell_source = b"# synthetic operator-reviewed shell fixture\npytest /tests/test_outputs.py -v\n"
    urls = []
    def fetch_fixture(request, **kwargs):
        urls.append(request.full_url)
        return io.BytesIO(shell_source if request.full_url.endswith("test.sh") else test_source)
    monkeypatch.setattr(adapter.urllib.request, "urlopen", fetch_fixture)
    evaluator_root = tmp_path / "evaluators"
    def execute(command, **kwargs):
        # A passing pytest process is insufficient when component reward is 0.
        logs = evaluator_root / task / "new-case-logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "reward.json").write_text('{"reward": 0.0}', encoding="utf-8")
        expected_flags = ["-v"] if protocol == "pytest_exit_status" else ["-q", "-s"]
        assert command[3:-1] == expected_flags
        return SimpleNamespace(returncode=0, stdout="FAIL: component_1_rule\n2 passed in 0.01s\n", stderr="")
    monkeypatch.setattr(adapter.subprocess, "run", execute)
    result = adapter.evaluate_native_case(case, evaluator_root, grading_protocol=protocol)
    raw = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
    assert len(urls) == 2 and urls[0].endswith("test_outputs.py") and urls[1].endswith("test.sh")
    assert raw["grading_protocol"] == protocol
    assert raw["grading_protocol_selection"] == "explicit_operator_selection_after_solver_stopped"
    assert raw["scoring_source_sha256"] == hashlib.sha256(shell_source).hexdigest()
    assert Path(result["report"]).with_name("test.original.sh").read_bytes() == shell_source
    if protocol == "pytest_exit_status":
        assert raw["reward"] == 1.0 and raw["pytest_counts"]["passed"] == 2
    else:
        assert raw["reward"] == 0.0 and "pytest_counts" not in raw


def test_ordinary_passing_tests_do_not_require_fabricated_components(tmp_path):
    task = "dbt-fix-product-metrics"
    inputs = native_summary_inputs(tmp_path, task, "ordinary-passing")
    agent_path = inputs[1] / "ordinary-passing-verified.json"
    agent = json.loads(agent_path.read_text(encoding="utf-8"))
    agent["final_build"] = {"success": True, "target_model_success": True}
    agent_path.write_text(json.dumps(agent), encoding="utf-8")
    verifier_path = inputs[2] / task / "ordinary-passing-evaluation.json"
    verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
    verifier.update({"grading_protocol": "pytest_exit_status", "pytest_counts": {"passed": 1, "failed": 0, "errors": 0, "skipped": 0}, "pytest_returncode": 0,
                     "components_passed": [], "components_failed": [], "stdout": "1 passed in 0.10s\n"})
    verifier_path.write_text(json.dumps(verifier), encoding="utf-8")
    output = tmp_path / "report.json"
    adapter.render_public_summary(*inputs, output, planned_tasks=(task,))
    row = json.loads(output.read_text(encoding="utf-8"))["records"][0]
    assert row["verification"]["passed"] and row["verification"]["valid_pytest_execution"]
    assert row["verification"]["components_passed"] == []


def test_api_exception_still_records_actual_elapsed_time_without_model_calls(tmp_path, monkeypatch):
    from datapatch import agent as agent_core, config as config_core, workspace as workspace_core
    task = adapter.LEGACY_TASKS[0]
    case = tmp_path / "interrupted"
    case.mkdir()
    (case / "instruction.md").write_text("Visible task", encoding="utf-8")
    (case / "native-case.json").write_text(json.dumps({"initialized": True, "task_id": task, "upstream_commit": adapter.PINNED_COMMIT, "mode": "native-test"}), encoding="utf-8")
    class FakeWorkspace:
        def __init__(self, root, project_dir, database_path):
            self.project_dir = project_dir
        def run_dbt(self, command):
            return {"success": True, "nodes": [{"id": "model.any_package.rpt_return_reconciliation", "status": "success"}]}
        def diff(self):
            return ""
    class FailingAgent:
        def __init__(self, *args, **kwargs):
            self.metrics = {"model_calls": 0, "tool_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0}
        def run(self, instruction):
            raise RuntimeError("HTTP 402 insufficient balance")
    monkeypatch.setattr(workspace_core, "Workspace", FakeWorkspace)
    monkeypatch.setattr(agent_core, "Agent", FailingAgent)
    monkeypatch.setattr(config_core.Settings, "load", classmethod(lambda cls: cls(api_key="unused-test-key")))
    ticks = iter((10.0, 12.5))
    monkeypatch.setattr(adapter.time, "monotonic", lambda: next(ticks))
    output = adapter.run_native_case(case, tmp_path / "results")
    report = json.loads(Path(output["report"]).read_text(encoding="utf-8"))
    assert report["result"]["metrics"]["elapsed_seconds"] == 2.5
    assert report["result"]["metrics"]["model_calls"] == 0
    assert "HTTP 402" in report["result"]["error"]
    assert report["final_build"]["target_model_success"]


def test_public_contract_install_preserves_bytes_scope_and_existing_content(tmp_path):
    case, contracts = tmp_path / "case", tmp_path / "contracts"
    case.mkdir()
    contracts.mkdir()
    original = b"Original public instruction\r\n"
    (case / "instruction.md").write_bytes(original)
    sql = b"-- visible project invariant\r\nselect 1 where false;\r\n"
    (contracts / "business.sql").write_bytes(sql)
    readme = "Keep business attribution complete.\n"
    (contracts / "README.md").write_bytes(readme.encode("utf-8"))
    (contracts / "nested").mkdir()
    (contracts / "nested/hidden.sql").write_text("must not copy", encoding="utf-8")
    (contracts / "unrelated.py").write_text("must not copy", encoding="utf-8")
    manifest = adapter.install_public_contracts(case, contracts)
    assert (case / "instruction.md").read_bytes() == original
    assert {path.name for path in (case / "checks").iterdir()} == {"business.sql", "README.md"}
    assert (case / "checks/business.sql").read_bytes() == sql
    assert manifest["contract_origin"] == "project_configuration"
    assert manifest["hidden_tests"] is False and manifest["reference_solution"] is False
    for item in manifest["files"]:
        assert item["source_sha256"] == item["installed_sha256"] == hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
    assert "Project-provided public business contract" in (case / "solver-instruction.md").read_text(encoding="utf-8")
    assert readme in (case / "solver-instruction.md").read_text(encoding="utf-8")
    assert adapter.install_public_contracts(case, contracts) == manifest
    (contracts / "business.sql").write_bytes(b"different")
    with pytest.raises(ValueError, match="overwrite"):
        adapter.install_public_contracts(case, contracts)
    assert (case / "checks/business.sql").read_bytes() == sql
    (contracts / "README.md").write_text("x" * 6001, encoding="utf-8")
    with pytest.raises(ValueError, match="6000"):
        adapter.install_public_contracts(case, contracts)


@pytest.mark.parametrize("with_contracts", [False, True])
@pytest.mark.parametrize("duckdb_timezone", [None, "UTC"])
def test_native_solver_instruction_and_starting_target_are_reported(tmp_path, monkeypatch, with_contracts, duckdb_timezone):
    from datapatch import agent as agent_core, config as config_core, workspace as workspace_core
    task = adapter.LEGACY_TASKS[0]
    case = tmp_path / "continuation"
    case.mkdir()
    (case / "instruction.md").write_text("Original ticket", encoding="utf-8")
    metadata = {"initialized": True, "task_id": task, "upstream_commit": adapter.PINNED_COMMIT, "mode": "native-test"}
    if duckdb_timezone is not None:
        metadata["runtime_settings"] = {"duckdb_timezone": duckdb_timezone}
    (case / "native-case.json").write_text(json.dumps(metadata), encoding="utf-8")
    target = case / "project" / adapter.PUBLIC_TASK_MODELS[task]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"select 'preloaded candidate'\n")
    start_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "README.md").write_text("Public business requirement", encoding="utf-8")
    (contracts / "visible.sql").write_bytes(b"select 1 where false\n")
    seen = []
    workspace_timezones = []
    class FakeWorkspace:
        def __init__(self, root, project_dir, database_path, *, duckdb_timezone=None):
            self.project_dir = project_dir
            workspace_timezones.append(duckdb_timezone)
        def run_dbt(self, command):
            return {"success": True, "nodes": [{"id": "model.any.rpt_return_reconciliation", "status": "success"}]}
        def diff(self):
            return ""
    class FakeAgent:
        def __init__(self, *args, **kwargs):
            self.metrics = {}
        def run(self, instruction):
            seen.append(instruction)
            target.write_bytes(b"select 'new candidate'\n")
            return {"metrics": {}, "stop_reason": "model_finished"}
    monkeypatch.setattr(workspace_core, "Workspace", FakeWorkspace)
    monkeypatch.setattr(agent_core, "Agent", FakeAgent)
    monkeypatch.setattr(config_core.Settings, "load", classmethod(lambda cls: cls(api_key="unused-test-key")))
    output = adapter.run_native_case(case, tmp_path / "results", contracts_dir=contracts if with_contracts else None)
    report = json.loads(Path(output["report"]).read_text(encoding="utf-8"))
    assert report["target_start"] == {"path": str(target), "exists": True, "sha256": start_sha}
    assert workspace_timezones == [duckdb_timezone]
    if duckdb_timezone is not None:
        assert report["runtime_settings"] == {"duckdb_timezone": "UTC"}
    assert Path(report["instruction_path"]).read_text(encoding="utf-8") == seen[0]
    assert (case / "instruction.md").read_text(encoding="utf-8") == "Original ticket"
    if with_contracts:
        assert "Public business requirement" in seen[0]
        assert report["public_contracts"]["contract_origin"] == "project_configuration"
        assert Path(report["instruction_path"]).name == "solver-instruction.md"
    else:
        assert seen == ["Original ticket"] and report["public_contracts"] is None
        assert not (case / "solver-instruction.md").exists() and not (case / "checks").exists()
