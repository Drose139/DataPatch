"""Tests exercise policy and feedback behavior, not purported model performance."""
from pathlib import Path

from datapatch.agent import Agent
from datapatch.config import Settings
from datapatch.evaluation import summarize


class FakeWorkspace:
    project_dir = Path("/workspace")
    root = Path("/workspace")
    database_path = Path("/workspace/warehouse.duckdb")

    def __init__(self):
        self.checks = 0

    def list_files(self):
        return {"files": ["models/report.sql"]}

    def search_schema(self):
        return {"tables": {}}

    def get_lineage(self):
        return {"nodes": []}

    def run_dbt(self, command):
        return {"success": True}

    def check_contracts(self):
        self.checks += 1
        return {"passed": self.checks >= 2, "checks": [{"name": "amount_contract", "passed": self.checks >= 2}]}


class FakeClient:
    def __init__(self):
        self.messages = []

    def complete(self, messages, tools=None):
        self.messages.append(list(messages))
        return {"message": {"role": "assistant", "content": "交付说明"}, "model": "test-double", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, "estimated_cost_usd": 0.001}


def test_verified_handoff_reopens_only_on_visible_feedback():
    client = FakeClient()
    events = []
    result = Agent(FakeWorkspace(), Settings(max_steps=3), "verified", events.append, client).run("Repair revenue")
    assert result["metrics"]["model_calls"] == 2
    assert result["visible_validation"]["passed"] is True
    assert "检查未通过" in client.messages[1][-1]["content"]
    assert not any("oracle" in str(message).lower() for message in client.messages)


def test_react_does_not_receive_verified_gate_feedback():
    client = FakeClient()
    workspace = FakeWorkspace()
    result = Agent(workspace, Settings(max_steps=3), "react", client=client).run("Repair revenue")
    assert result["metrics"]["model_calls"] == 1
    assert workspace.checks == 0


def test_short_repair_reserves_calls_for_executable_gates():
    class ShortWorkspace(FakeWorkspace):
        def diff(self):
            return "--- a/models/report.sql\n+++ b/models/report.sql\n-select 0\n+select 1\n"

    events = []
    result = Agent(ShortWorkspace(), Settings(max_steps=4), "verified", events.append, FakeClient()).run("Repair against public contracts")
    assert result["metrics"]["model_calls"] == 2
    assert result["visible_validation"]["passed"] is True
    assert result["candidate_review"] is None
    assert not any(event.get("type") == "review" for event in events)


def test_all_repeats_success_is_not_at_least_one_success():
    records = [{"mode": "verified", "task_id": "a", "status": "completed", "final_build": {"success": True}, "verification": {"passed": x}, "metrics": {}} for x in [True, False, True]]
    result = summarize(records)[0]
    assert result["task_success_rate"] == 0.6667
    assert result["all_repeats_success_rate"] == 0

