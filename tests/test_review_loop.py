import json
from pathlib import Path

from datapatch.agent import Agent
from datapatch.config import Settings


class Workspace:
    root = project_dir = Path("/workspace")
    database_path = root / "warehouse.duckdb"
    original = {"models/report.sql": "select 0 as ratio"}

    def __init__(self):
        self.sql = ""

    def list_files(self):
        return {"files": ["models/report.sql"]}

    def diff(self):
        return "--- a/models/report.sql\n+++ b/models/report.sql\n+" + self.sql if self.sql else ""

    def call(self, name, arguments):
        assert name == "write_model"
        self.sql = arguments["content"]
        return {"written": arguments["path"]}

    def run_dbt(self, command):
        return {"success": True}

    def check_contracts(self):
        return {"passed": True, "available": False, "checks": []}


class Client:
    def __init__(self):
        self.executions = 0
        self.review_messages = []
        self.executor_saw_findings = False

    def complete(self, messages, tools):
        if tools is None:
            self.review_messages = messages
            message = {"role": "assistant", "content": json.dumps({"verdict": "revise", "summary": "Ratio uses an unjustified default", "findings": [{"requirement_quote": "Repair ratio", "concern": "Wrong ratio", "evidence": "constant 0", "validation": "Compute from source amounts"}]})}
        else:
            self.executions += 1
            if self.executions == 3:
                self.executor_saw_findings = any("Wrong ratio" in str(item.get("content")) for item in messages)
            if self.executions <= 3:
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": str(self.executions), "type": "function", "function": {"name": "write_model", "arguments": json.dumps({"path": "models/report.sql", "content": "select 0 as ratio" if self.executions <= 2 else "select paid / nullif(requested, 0) as ratio"})}}]}
            else:
                message = {"role": "assistant", "content": "Candidate ready for independent evaluation"}
        return {"message": message, "model": "test-double", "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}, "estimated_cost_usd": 0.001}


def test_review_is_within_shared_budget_and_findings_reach_executor():
    client, workspace = Client(), Workspace()
    # Six calls enable review; two executor turns leave four shared calls,
    # then the reviewer, correction, and handoff consume three of them.
    result = Agent(workspace, Settings(max_steps=6), "verified", client=client).run("Repair ratio without changing coverage")
    assert result["metrics"]["model_calls"] == 5
    assert result["metrics"]["model_calls"] <= 6
    assert result["metrics"]["review_calls"] == 1
    assert client.executor_saw_findings
    assert "nullif" in workspace.sql
    assert result["candidate_review"]["patch_changed_since_review"] is True
    assert result["stop_reason"] == "model_finished"


def test_tight_budget_never_spends_an_extra_review_call():
    result = Agent(Workspace(), Settings(max_steps=2), "verified", client=Client()).run("Repair ratio")
    assert result["metrics"]["model_calls"] == 2
    assert result["candidate_review"] is None
    assert result["stop_reason"] == "step_limit"


def test_prolonged_exploration_enters_delivery_stage_then_restores_tools():
    workspace = Workspace()
    reads, restored = [], []
    original_call = workspace.call

    def call(name, arguments):
        if name == "query_sql":
            reads.append(arguments)
            return {"columns": ["n"], "rows": [[0]], "truncated": False}
        return original_call(name, arguments)

    workspace.call = call

    class ExploringClient:
        def complete(self, messages, tools):
            names = {tool["function"]["name"] for tool in (tools or [])}
            if tools is None:
                message = {"role": "assistant", "content": '{"verdict":"approve","findings":[],"summary":"No concrete concern"}'}
            elif workspace.sql:
                restored.append("query_sql" in names)
                message = {"role": "assistant", "content": "Candidate saved"}
            else:
                name = "query_sql" if "query_sql" in names else "write_model"
                arguments = {"sql": "select 0"} if name == "query_sql" else {"path": "models/report.sql", "content": "select 1 as ratio"}
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": str(len(reads)), "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}
            return {"message": message, "usage": {}, "estimated_cost_usd": 0}

    result = Agent(workspace, Settings(max_steps=14), "verified", client=ExploringClient()).run("Repair ratio")
    assert len(reads) == 8
    assert workspace.sql
    assert restored == [True]
    assert result["metrics"]["delivery_stage_entries"] == 1
    assert result["metrics"]["model_calls"] <= 14
