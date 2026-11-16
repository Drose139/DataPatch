from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("public_suite", Path(__file__).resolve().parents[1] / "scripts/run_public_suite.py")
suite = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(suite)


@pytest.fixture
def mocked_suite(tmp_path, monkeypatch):
    monkeypatch.setattr(suite, "ROOT", tmp_path)
    monkeypatch.setattr(suite, "source_digest", lambda: "a" * 64)
    settings = SimpleNamespace(model="deepseek-flash", thinking_enabled=True, reasoning_effort="high", max_output_tokens=8192, input_rate=0.30, output_rate=1.20)
    monkeypatch.setattr(suite.Settings, "load", staticmethod(lambda: settings))
    snapshot = tmp_path / "frozen.zip"
    with zipfile.ZipFile(snapshot, "w") as archive:
        archive.writestr("source-manifest.json", json.dumps({"core_source_sha256": "a" * 64}))
    state = {"events": [], "fail_run": None}
    original_render = suite.adapter.render_public_summary

    def prepare(source, case, task):
        assert list((tmp_path / "artifacts/protocols").glob("*.json")), "Protocol must exist before any task begins"
        state["events"].append((task, "prepare"))
        case.mkdir(parents=True)
        (case / "native-case.json").write_text(json.dumps({"task_id": task, "base_build": "mock inputs", "runtime": {}}), encoding="utf-8")

    def run(case, result_root, **kwargs):
        task = json.loads((case / "native-case.json").read_text(encoding="utf-8"))["task_id"]
        state["events"].append((task, "run"))
        assert kwargs == {"mode": "verified", "max_steps": 12, "budget_usd": 0.125, "source_snapshot": snapshot}
        if task == state["fail_run"]:
            raise RuntimeError("Simulated API transport failure")
        result_root.mkdir(parents=True, exist_ok=True)
        (result_root / (case.name + "-verified.json")).write_text(json.dumps({"model": settings.model, "max_steps": 12, "budget_usd": 0.125,
            "source_sha256": "a" * 64, "source_snapshot": str(snapshot), "final_build": {"success": True},
            "result": {"stop_reason": "model_finished", "metrics": {"model_calls": 1, "tool_calls": 1, "prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12, "estimated_cost_usd": 0.01, "elapsed_seconds": 0.1}}}), encoding="utf-8")

    def evaluate(case, evaluator_root):
        task = json.loads((case / "native-case.json").read_text(encoding="utf-8"))["task_id"]
        state["events"].append((task, "evaluate"))
        failed = task == state["fail_run"]
        directory = evaluator_root / task
        directory.mkdir(parents=True, exist_ok=True)
        raw = {"reward": 0.0 if failed else 1.0, "returncode": 1 if failed else 0,
               "components_passed": [] if failed else ["component_1_model_compiles"],
               "components_failed": ["component_1_model_compiles"] if failed else [],
               "stdout": "1 failed in 0.1s\n" if failed else "1 passed in 0.1s\n"}
        (directory / (case.name + "-evaluation.json")).write_text(json.dumps(raw), encoding="utf-8")

    def render(case, results, evaluators, output, **kwargs):
        task = json.loads((case / "native-case.json").read_text(encoding="utf-8"))["task_id"]
        state["events"].append((task, "render"))
        return original_render(case, results, evaluators, output, **kwargs)

    monkeypatch.setattr(suite.adapter, "prepare_native_case", prepare)
    monkeypatch.setattr(suite.adapter, "run_native_case", run)
    monkeypatch.setattr(suite.adapter, "evaluate_native_case", evaluate)
    monkeypatch.setattr(suite.adapter, "render_public_summary", render)
    return tmp_path, snapshot, settings, state


def test_four_tasks_are_sequential_preregistered_capped_and_never_start_round_two(mocked_suite):
    root, snapshot, _, state = mocked_suite
    result = suite.run_suite(1, snapshot)
    assert state["events"] == [(task, stage) for task in suite.TASK_NAMES for stage in ("prepare", "run", "evaluate", "render")]
    protocol = json.loads(Path(result["protocol"]).read_text(encoding="utf-8"))
    report = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
    assert protocol["round_budget_usd"] == 0.5 and protocol["maximum_two_round_budget_usd"] == 1.0
    assert report["planned_trials"] == 4 and len(report["records"]) == 4 and result["all_passed"]
    assert not list(root.rglob("*round2*"))
    with pytest.raises(ValueError, match="already"):
        suite.run_suite(1, snapshot)
    assert len(state["events"]) == 16


def test_explicit_subset_keeps_its_denominator_and_budget(mocked_suite):
    _, snapshot, _, state = mocked_suite
    task = "dbt-fix-inventory-model"
    result = suite.run_suite(2, snapshot, (task,))
    protocol = json.loads(Path(result["protocol"]).read_text(encoding="utf-8"))
    assert protocol["task_ids"] == [task] and protocol["round_budget_usd"] == 0.125
    assert result["planned_trials"] == 1 and len(state["events"]) == 4


@pytest.mark.parametrize("field,value", [("model", "deepseek-v4-pro"), ("thinking_enabled", False), ("reasoning_effort", "max"),
                                         ("max_output_tokens", 16384), ("input_rate", 0.01), ("output_rate", 0.01)])
def test_pro_or_polluted_settings_are_rejected_before_any_task(mocked_suite, field, value):
    root, snapshot, settings, state = mocked_suite
    setattr(settings, field, value)
    with pytest.raises(ValueError):
        suite.run_suite(1, snapshot)
    assert state["events"] == [] and not (root / "artifacts/protocols").exists()


def test_unknown_round_and_existing_partial_run_are_not_retried(mocked_suite):
    root, snapshot, _, state = mocked_suite
    with pytest.raises(ValueError, match="round"):
        suite.run_suite(3, snapshot)
    result_root = root / "external/native-results"
    result_root.mkdir(parents=True)
    (result_root / "refund-v41-flash-r1-verified.jsonl").write_text("partial charged call\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Existing"):
        suite.run_suite(1, snapshot)
    assert not state["events"]


def test_failure_still_gets_verifier_and_fixed_denominator_without_rerun(mocked_suite):
    _, snapshot, _, state = mocked_suite
    state["fail_run"] = "dbt-fix-refund-reconciliation"
    result = suite.run_suite(1, snapshot)
    report = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
    assert not result["all_passed"] and report["planned_trials"] == len(report["records"]) == 4
    failed = next(row for row in report["records"] if row["task_id"] == state["fail_run"])
    assert failed["status"] == "failed" and failed["raw_verifier"]["reward"] == 0
    assert failed["verification"]["passed"] is False
    assert len(state["events"]) == 16  # one attempt, including scoring, per task


def test_source_mismatch_is_rejected_without_task_or_protocol(mocked_suite, monkeypatch):
    root, snapshot, _, state = mocked_suite
    monkeypatch.setattr(suite, "source_digest", lambda: "b" * 64)
    with pytest.raises(ValueError, match="snapshot"):
        suite.run_suite(1, snapshot)
    assert not state["events"] and not (root / "artifacts/protocols").exists()
