"""Final scoring must reject broken patches even when stale tables look correct."""

import pytest

import datapatch.service as service_module
from datapatch.config import Settings
from datapatch.evaluation import summarize
from datapatch.service import RunService


@pytest.mark.parametrize("build_succeeds,late_failure", [(False, False), (True, False), (True, True)])
def test_final_score_requires_build_and_independent_output_checks(tmp_path, monkeypatch, build_succeeds, late_failure):
    settings = Settings(api_key="unit-test-placeholder", artifacts_dir=tmp_path)
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(service_module, "create_task", lambda task_id, workspace: {})

    class FakeWorkspace:
        def __init__(self, root, database_path=None):
            self.root = root

        def run_dbt(self, command):
            return {"success": build_succeeds if command == "build" else True}

        def check_contracts(self):
            return {"passed": True, "checks": []}

        def diff(self):
            return "+ select * from" if not build_succeeds else "+ select correct_output"

    class FakeAgent:
        def __init__(self, workspace, settings, mode, emit):
            pass

        def run(self, instruction):
            return {"final_answer": "交付补丁", "metrics": {"model_calls": 0, "total_tokens": 0}}

    oracle_checks = [{"name": "all_row_values", "passed": True, "expected": "Python oracle", "actual": "all rows match"}]
    monkeypatch.setattr(service_module, "Workspace", FakeWorkspace)
    monkeypatch.setattr(service_module, "Agent", FakeAgent)
    monkeypatch.setattr(service_module, "verify_task", lambda task_id, workspace: {"passed": True, "checks": oracle_checks, "summary": "All independent checks passed"})
    if late_failure:
        original_write = service_module.write_json
        failed_once = []

        def persistence_failure_after_grading(path, data):
            if path.name == "run.json" and data.get("status") == "completed" and not failed_once:
                failed_once.append(True)
                raise PermissionError("simulated late persistence failure")
            return original_write(path, data)

        monkeypatch.setattr(service_module, "write_json", persistence_failure_after_grading)

    service = RunService(settings)
    try:
        record = service.run_sync("revenue_fanout_dev", mode="react", max_steps=2)
    finally:
        service.pool.shutdown(wait=True)

    # Execution completion is separate from task correctness.
    assert record["status"] == ("failed" if late_failure else "completed")
    assert record["verification"]["passed"] is (build_succeeds and not late_failure)
    checks = record["verification"]["checks"]
    if late_failure:
        assert checks[0]["name"] == "execution_completed"
        assert checks[0]["passed"] is False
        checks = checks[1:]
    assert checks[0] == {"name": "final_build_success", "passed": build_succeeds, "expected": True, "actual": build_succeeds}
    assert checks[1:] == oracle_checks
    assert record["checks"] == record["verification"]["checks"]
    assert summarize([record])[0]["passed"] == int(build_succeeds and not late_failure)
    if not build_succeeds:
        assert "stale tables" in record["verification"]["summary"]
    # Adding the build check must not mutate the oracle's evidence.
    assert len(oracle_checks) == 1
