"""Review output is advisory; malformed output must never imply approval."""
import json

from datapatch.review import review_candidate


class Candidate:
    original = {"models/report.sql": "select customer_id from orders where status != 'CANCELLED'"}

    def diff(self):
        return "--- a/models/report.sql\n+++ b/models/report.sql\n-select customer_id from orders where status != 'CANCELLED'\n+select customer_id from orders where upper(status) != 'CANCELLED'\n"


def test_review_receives_original_ticket_and_candidate_without_evaluator():
    seen = []

    def respond(messages, tools):
        seen.extend(messages)
        assert tools is None
        return {"message": {"content": json.dumps({"verdict": "revise", "summary": "Unrequested population change", "findings": [{"requirement_quote": "retain existing customer population", "concern": "Case normalization", "evidence": "upper(status)", "validation": "Compare retained customer keys"}]})}}

    result = review_candidate(Candidate(), "Add a safe ratio; retain existing customer population", {"README": "Business contract"}, respond)
    content = json.loads(seen[1]["content"])
    assert content["original_changed_models"]["models/report.sql"].endswith("status != 'CANCELLED'")
    assert "upper(status)" in content["candidate_patch"]
    assert content["ticket"].startswith("Add a safe ratio")
    assert "verification" not in content
    assert result["verdict"] == "revise"
    assert result["advisory_only"] is True
    assert result["hidden_feedback_used"] is False


def test_malformed_review_is_inconclusive():
    for raw in ("looks good", "[]", '{"verdict":"revise","findings":[]}', '{"verdict":"revise","findings":[{}]}', '{"verdict":"approve","findings":"none"}'):
        result = review_candidate(Candidate(), "ticket", {}, lambda messages, tools: {"message": {"content": raw}})
        assert result["verdict"] == "inconclusive"


def test_fenced_valid_json_is_accepted():
    raw = '```json\n{"verdict":"approve","findings":[],"summary":"No concrete concern"}\n```'
    result = review_candidate(Candidate(), "ticket", {}, lambda messages, tools: {"message": {"content": raw}})
    assert result["verdict"] == "approve"
    assert result["advisory_only"] is True


def test_review_does_not_approve_when_complete_requirements_cannot_fit():
    calls = []
    result = review_candidate(Candidate(), '"' * 50000, {"readme": {"content": "Required business rules"}}, lambda *args: calls.append(args))
    assert result["verdict"] == "inconclusive"
    assert result["skipped"] is True
    assert calls == []


def test_review_rejects_finding_that_cites_an_invented_requirement():
    raw = json.dumps({"verdict": "revise", "findings": [{"requirement_quote": "Must add watermark optimization", "concern": "Not optimized", "evidence": "No watermark", "validation": "Add watermark"}]})
    result = review_candidate(Candidate(), "Repair correctness", {"readme": {"content": "Preserve incremental materialization"}}, lambda messages, tools: {"message": {"content": raw}})
    assert result["verdict"] == "inconclusive"
    assert result["findings"] == []
