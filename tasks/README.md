# DataPatch synthetic task suite

This is a reproducible local portfolio evaluation suite, **not a public external benchmark**. It contains six task families, each instantiated with a development seed and a held-out data seed (12 task IDs). The held-out split changes records, identifiers, amounts, and event order while preserving the task's semantics and buggy implementation. It tests robustness to new data, not unseen defect classes or new codebases.

| Family | Required engineering behavior |
|---|---|
| `revenue_fanout` | Preserve order grain when aggregating items and split payments |
| `refund_reconciliation` | Include every refund, preserve cancelled-order refunds, avoid zero-denominator NaN |
| `local_day_boundary` | Apply fixed UTC+08:00 business days at month/year boundaries |
| `repeat_customer_identity` | Resolve multiple accounts to a stable person ID |
| `incremental_replay` | Retain incremental materialization and remain correct when replayed |
| `build_customer_ltv` | Build a customer mart across orders, items, identity and refunds |

`list_tasks()` provides exact IDs and public metadata. `create_task(task_id, workspace)` creates an isolated dbt/DuckDB project with six CSV seeds, model SQL, partial visible invariant tests, an absolute database path, and a business contract. No gold rows, expected result tables, Python oracle, or reference repair are copied into that workspace.

`verify_task(task_id, workspace)` runs **outside the agent environment**. It regenerates the immutable source fixture and computes expected rows in Python, checks source-file integrity, then compares the output schema, row count and every value. Incremental tasks also rerun the candidate dbt model once to verify replay idempotency; the candidate database is intentionally changed during this test. Reference repairs exist only in the repository's tests, never in generated agent workspaces.

Visible checks return violation rows; zero rows means the check passes. Their SQL uses dbt `ref()` syntax and is intended for `dbt test` or a trusted resolver. Passing visible checks alone does not prove full correctness.

For an external comparison, keep results on Snowflake's public `data-eng-bench` or any other unmodified external subset in a separate report. Do not combine these synthetic tasks with an external benchmark score or claim production incident resolution from this suite.
