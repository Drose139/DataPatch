"""A requirements-based second pass over a candidate, with no grading access.

The reviewer uses the same configured model and the same total call budget.
Its opinion is visible feedback, never a replacement for execution or grading.
"""
from __future__ import annotations

import json
import hashlib
from typing import Callable


REVIEW_PROMPT = """You review a candidate dbt SQL patch against a public engineering ticket.
The original SQL can contain bugs. Preserve behavior the ticket does not authorize changing.
First extract the requested changes and preserved business rules from the ticket and project README.
Then compare the original SQL and actual patch. Check joins, filters, grouping, numeric and NULL
semantics against those rules. Do not assume normalization, new exclusions, or convenient defaults
are authorized. A successful build, unchanged row count or an empty test list is not semantic proof.
For enumerated filters, compare literal matching to the ticket: extra case conversion can exclude other values.
For monetary metrics, check whether source totals already encode discounts or taxes before approving quantity
times price as a substitute. Request a source comparison when the mapping is unsupported by available evidence.
Report only concrete, evidenced concerns with file/SQL expressions and an actionable validation.
Use relationship_checks to question silently dropped facts or duplicate lookups. Check the relevant filtered
population and alternate bridge paths; non-NULL keys and complete dimension output alone do not prove coverage.
For each finding quote the exact public requirement or preserved original SQL it violates.
Do not promote performance preferences or hypothetical edge cases to correctness requirements.
In particular, a repair can intentionally change buggy joins/filters when the README authorizes it.
Performance preferences matter only when the ticket explicitly makes them a requirement.
Do not invent expected values, hidden tests, or a reference solution. If evidence is insufficient,
say so. You cannot execute tools in this review pass; the executor can investigate your findings.
Return ONLY JSON: {"verdict":"approve|revise|inconclusive", "summary":"...",
"findings":[{"requirement_quote":"exact quote from the ticket, README or original SQL", "concern":"...","evidence":"...","validation":"..."}]}.
Use at most 5 findings. An approve verdict is an advisory opinion, not task success.
"""


def review_candidate(workspace, instruction: str, task_context: dict, respond: Callable) -> dict:
    patch = workspace.diff()
    # Only changed files, original code, and visible task context. Never inspect
    # final verification, reference solutions, hidden tests, or prior runs.
    originals = {}
    for path, content in getattr(workspace, "original", {}).items():
        if f"--- a/{path}" in patch:
            originals[path] = content
    context = {
        "ticket": instruction,
        "visible_task_context": task_context,
        "original_changed_models": originals,
        "candidate_patch": patch,
    }
    encode = lambda data: json.dumps(data, ensure_ascii=False, default=str)
    # This is a serialized character bound, not a tokenizer-based token limit.
    truncated = len(encode(context)) > 42000
    if truncated:
        context = {"ticket": instruction, "candidate_patch": patch,
                   "readme": task_context.get("readme"),
                   "original_changed_models": originals,
                   "context_truncated": True}
        # Remove auxiliary schema/lineage before touching requirements/code.
        # If essential material cannot fit, report inconclusive without a call.
        if len(encode(context)) > 42000:
            return {"verdict": "inconclusive", "summary": "Complete requirements and candidate exceed the review context budget; review skipped rather than approving partial evidence.", "findings": [], "context_truncated": True, "advisory_only": True, "hidden_feedback_used": False, "skipped": True}
    response = respond([
        {"role": "system", "content": REVIEW_PROMPT},
        {"role": "user", "content": encode(context)},
    ], None)
    raw = response["message"].get("content") or ""
    cleaned = raw.strip()
    if cleaned.startswith("```") and "\n" in cleaned:
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict) or parsed.get("verdict") not in {"approve", "revise", "inconclusive"}:
            raise ValueError("Review verdict is invalid")
        findings = parsed.get("findings", [])
        if not isinstance(findings, list) or not all(isinstance(x, dict) for x in findings):
            raise ValueError("Review findings are invalid")
        readme = task_context.get("readme") or {}
        public_text = instruction + "\n" + str(readme.get("content", "")) + "\n" + "\n".join(originals.values())
        normalize = lambda text: " ".join(text.split()).casefold()
        public_text = normalize(public_text)
        findings = [row for row in findings if all(isinstance(row.get(key), str) and row[key].strip() for key in ("requirement_quote", "concern", "evidence", "validation")) and normalize(row["requirement_quote"]) in public_text]
        verdict = parsed["verdict"]
        if verdict == "revise" and not findings:
            verdict = "inconclusive"
        result = {"verdict": verdict, "summary": str(parsed.get("summary", ""))[:2000],
                  "findings": [{str(k): str(v)[:2000] for k, v in row.items() if k in {"requirement_quote", "concern", "evidence", "validation"}} for row in findings[:5]]}
    except (ValueError, TypeError):
        result = {"verdict": "inconclusive", "summary": "Review returned invalid structured output; no approval inferred.", "findings": [], "raw_response": raw[:3000]}
    return {**result, "candidate_sha256": hashlib.sha256(patch.encode()).hexdigest(), "context_truncated": truncated, "advisory_only": True, "hidden_feedback_used": False}
