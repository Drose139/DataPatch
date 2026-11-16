"""Synthetic reasoning is retained for API continuity, never emitted for replay."""
from copy import deepcopy
import json
import pytest

from datapatch.agent import Agent
from datapatch.config import Settings
from datapatch.provider import BudgetExceeded, ModelError


class FakeWorkspace:
    def __init__(self, root):
        self.root = self.project_dir = root
        self.database_path = root / "warehouse.duckdb"

    def list_files(self):
        return {"files": ["models/report.sql"]}

    def diff(self):
        return ""

    def call(self, name, arguments):
        assert name == "query_sql"
        assert arguments == {"sql": "select 1"}
        return {"columns": ["value"], "rows": [[1]], "truncated": False}


class ScriptedClient:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def complete(self, messages, tools=None):
        self.requests.append({"messages": deepcopy(messages), "tools": deepcopy(tools)})
        return deepcopy(self.responses[len(self.requests) - 1])


def response(reasoning, content, finish_reason, call_id=None):
    message = {"role": "assistant", "reasoning_content": reasoning, "content": content}
    if call_id:
        message["tool_calls"] = [{
            "id": call_id,
            "type": "function",
            "function": {"name": "query_sql", "arguments": '{"sql":"select 1"}'},
        }]
    return {
        "message": message,
        "model": "synthetic-model",
        "finish_reason": finish_reason,
        "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18,
                  "completion_tokens_details": {"reasoning_tokens": 6}},
        "estimated_cost_usd": 0.001,
    }


def test_tool_history_keeps_full_reasoning_even_after_a_turn_without_tools(tmp_path):
    # Longer than the tool-result clipping bound, so accidental clipping is caught.
    thoughts = ["synthetic-private-a:" + "test reasoning\n" * 2000,
                "synthetic-private-b", "synthetic-private-c", "synthetic-private-d"]
    client = ScriptedClient([
        response(thoughts[0], None, "tool_calls", "call-a"),
        response(thoughts[1], "Incomplete handoff", "length"),
        response(thoughts[2], None, "tool_calls", "call-c"),
        response(thoughts[3], "完成：已检查查询结果。", "stop"),
    ])
    events = []

    result = Agent(FakeWorkspace(tmp_path), Settings(max_steps=4), "react", events.append, client).run("Inspect SQL")

    assert len(client.requests) == 4
    for index, request in enumerate(client.requests):
        assert request["tools"]
        assistants = [message for message in request["messages"] if message["role"] == "assistant"]
        assert [message["reasoning_content"] for message in assistants] == thoughts[:index]
    tool_replies = [message for message in client.requests[-1]["messages"] if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in tool_replies] == ["call-a", "call-c"]
    assert all(json.loads(message["content"])["rows"] == [[1]] for message in tool_replies)
    assert result["stop_reason"] == "model_finished"
    assert result["final_answer"] == "完成：已检查查询结果。"
    assert result["metrics"]["model_calls"] == 4
    assert result["metrics"]["tool_calls"] == 2
    assert result["metrics"]["output_limit_hits"] == 1
    model_events = [event for event in events if event["type"] == "model"]
    assert [event["finish_reason"] for event in model_events] == ["tool_calls", "length", "tool_calls", "stop"]
    assert all(event["usage"]["completion_tokens_details"]["reasoning_tokens"] == 6 for event in model_events)
    public_records = json.dumps({"events": events, "result": result}, ensure_ascii=False)
    assert "reasoning_content" not in public_records
    assert all(thought.split(":", 1)[0] not in public_records for thought in thoughts)


def test_length_without_tools_exhausts_budget_without_claiming_model_finished(tmp_path):
    client = ScriptedClient([response("synthetic-private-truncated", "Unfinished answer", "length")])
    events = []

    result = Agent(FakeWorkspace(tmp_path), Settings(max_steps=1), "react", events.append, client).run("Repair SQL")

    assert result["stop_reason"] == "step_limit"
    assert result["final_answer"] != "Unfinished answer"
    assert result["metrics"]["output_limit_hits"] == 1
    assert result["metrics"]["model_calls"] == 1
    assert result["metrics"]["tool_calls"] == 0
    assert events[-1]["type"] == "final"
    assert events[-1]["stop_reason"] == "step_limit"
    assert next(event for event in events if event["type"] == "model")["finish_reason"] == "length"


def test_pre_request_budget_stop_is_bounded_execution_without_a_fake_model_call(tmp_path):
    class StopsAfterOne(ScriptedClient):
        def complete(self, messages, tools=None):
            if self.requests:
                raise BudgetExceeded("No allowance for another request")
            return super().complete(messages, tools)

    client = StopsAfterOne([response("private", None, "tool_calls", "call-a")])
    events = []
    result = Agent(FakeWorkspace(tmp_path), Settings(max_steps=4), "react", events.append, client).run("Inspect SQL")
    assert result["stop_reason"] == "cost_limit"
    assert "error" not in result
    assert result["metrics"]["model_calls"] == len(client.requests) == 1
    assert result["metrics"]["tool_calls"] == 1
    assert len([event for event in events if event["type"] == "model"]) == 1
    assert events[-1]["stop_reason"] == "cost_limit"
    assert "独立构建和验收" in result["final_answer"]


def test_provider_errors_remain_execution_errors(tmp_path):
    class FailedClient:
        def complete(self, messages, tools=None):
            raise ModelError("HTTP 402")

    with pytest.raises(ModelError, match="402"):
        Agent(FakeWorkspace(tmp_path), Settings(), "react", client=FailedClient()).run("Inspect SQL")
