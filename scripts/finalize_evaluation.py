"""Apply the recorded final-build criterion after an in-flight scoring fix.

Preserves the pre-amendment report. No model calls or hidden-test feedback occur.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from datapatch.config import ROOT
from datapatch.evaluation import render_report, summarize
from datapatch.service import write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    args = parser.parse_args()
    path = ROOT / "artifacts/evaluations" / f"{args.name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["status"] not in {"completed", "budget_stopped"}:
        raise RuntimeError("Wait for the fixed-protocol batch to finish before finalizing.")
    if data.get("grading_amendment"):
        print("Scoring amendment already applied")
        return
    write_json(path.with_name(path.stem + "_unamended.json"), deepcopy(data))
    changed_grades = 0
    for record in data["records"]:
        verification = record.get("verification")
        if verification is None:
            continue
        build_success = bool((record.get("final_build") or {}).get("success"))
        original_pass = bool(verification.get("passed"))
        execution_completed = record.get("status") == "completed"
        new_pass = original_pass and build_success and execution_completed
        changed_grades += int(original_pass != new_pass)
        checks = [check for check in verification.get("checks", []) if check["name"] not in {"final_build_success", "execution_completed"}]
        verification["checks"] = [{"name": "execution_completed", "passed": execution_completed, "expected": True, "actual": execution_completed}, {"name": "final_build_success", "passed": build_success, "expected": True, "actual": build_success}, *checks]
        verification["passed"] = new_pass
        if not build_success:
            verification["summary"] = "Final build failed; persisted output alone is not sufficient. " + verification.get("summary", "")
        if not execution_completed:
            verification["summary"] = "Execution failed; saved output checks do not establish completed delivery. " + verification.get("summary", "")
        record["checks"] = verification["checks"]
        record["grading_amendment"] = "Execution must complete and final build must succeed as well as independent output checks; uses saved evidence only."
        record_path = ROOT / "artifacts/runs" / record["run_id"] / "run.json"
        if record_path.exists():
            write_json(record_path, record)
            write_json(record_path.parent / "verification.json", verification)
    data["summary"] = summarize(data["records"])
    data["grading_amendment"] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": "Code review identified stale correct tables after a failed build and one Windows persistence failure after correct output verification. Final grades require completed execution, saved final_build.success and independent output verification. The infrastructure failure remains in the denominator.",
        "changed_trial_grades": changed_grades,
        "no_model_rerun": True,
        "original_report": path.with_name(path.stem + "_unamended.json").name,
    }
    write_json(path, data)
    render_report(data, path.with_suffix(".md"))
    print(json.dumps({"trials": len(data["records"]), "changed_trial_grades": changed_grades, "summary": data["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
