"""Reproducible, execution-graded retail tasks.

Only ``create_task`` output is delivered to an agent. Generators and Python
oracles stay in the evaluator process; no gold rows or repair scripts are copied
into a task workspace. These are synthetic portfolio tasks, not an external
benchmark or a claim of production incident coverage.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any


_SPECS: dict[str, dict[str, Any]] = {
    "revenue_fanout": {
        "title": "Repair inflated order revenue", "difficulty": "medium",
        "description": "Order revenue and payment totals are inflated after a report refactor. Preserve one row per completed order and reconcile both totals to the underlying records.",
        "output": "order_revenue", "columns": ["order_id", "gross_cents", "paid_cents"],
        "contract": "One row per completed order. gross_cents is sum(quantity * unit_price_cents) over its items; paid_cents is sum(amount_cents) over its payments. Different payment and item counts must not inflate either total. Include zero-value orders.",
    },
    "refund_reconciliation": {
        "title": "Repair refund coverage and ratios", "difficulty": "medium",
        "description": "The refund operations report omits records and contains invalid completion ratios. Repair coverage and numeric edge cases without changing source data.",
        "output": "refund_reconciliation", "columns": ["refund_id", "order_id", "requested_cents", "paid_cents", "completion_ratio"],
        "contract": "Exactly one row for EVERY source refund, including refunds associated with cancelled orders and requests for zero cents. Preserve the integer amounts. completion_ratio = paid_cents / requested_cents when requested_cents > 0; otherwise it is 0.0. Ratios must be finite.",
    },
    "local_day_boundary": {
        "title": "Repair business-day sales boundaries", "difficulty": "medium",
        "description": "Daily sales disagree with the business clock around midnight. Rebuild the report using the documented UTC+08:00 day, not the timestamp's UTC calendar date.",
        "output": "daily_sales", "columns": ["business_day", "order_count", "gross_cents"],
        "contract": "ordered_at is a naive UTC timestamp. The business timezone is fixed UTC+08:00 with no DST. Group completed orders by date(ordered_at + 8 hours), count orders exactly once, and sum their item revenue. Emit only days containing completed orders.",
    },
    "repeat_customer_identity": {
        "title": "Repair repeat-customer identity", "difficulty": "medium",
        "description": "Repeat purchase reporting splits the same person across order-specific customer accounts. Use the stable person identity and correctly aggregate completed orders.",
        "output": "customer_repeat", "columns": ["person_id", "order_count", "gross_cents", "is_repeat"],
        "contract": "customers.customer_id identifies an account; person_id identifies a person and can map from multiple accounts. For people with at least one completed order, emit one row per person, order_count, total item revenue, and is_repeat = 1 iff order_count >= 2, else 0. Cancelled orders do not count.",
    },
    "incremental_replay": {
        "title": "Repair incremental replay idempotency", "difficulty": "hard",
        "description": "An incremental current-order-state model duplicates rows when the same delivery is replayed. Preserve incremental materialization while making repeated runs idempotent.",
        "output": "order_state", "columns": ["order_id", "status", "net_cents"],
        "contract": "Preserve materialized='incremental'. Choose the newest event per order by updated_at DESC, then event_id DESC for timestamp ties. Emit order_id, status, net_cents from that event. Running dbt run --select order_state again against identical input must preserve exactly the same rows and values. The evaluator independently reruns the model to test this.",
    },
    "build_customer_ltv": {
        "title": "Build a customer net-revenue mart", "difficulty": "hard",
        "description": "Implement a missing customer finance mart combining stable customer identity, completed orders, items, and paid refunds. The supplied model is only an empty schema stub.",
        "output": "customer_ltv", "columns": ["person_id", "order_count", "gross_cents", "refund_cents", "net_cents"],
        "contract": "For each person with a completed order, aggregate completed-order counts and item revenue. refund_cents is the sum of paid_cents from every refund attached to those completed orders, regardless of refund status; absent refunds contribute zero. net_cents = gross_cents - refund_cents. Preserve zero-revenue people and all completed orders. One row per stable person_id.",
    },
}


def list_tasks() -> list[dict[str, Any]]:
    """Return the public catalog; holdout changes data, not task semantics."""
    return [
        {"id": f"{category}_{split}", "title": spec["title"],
         "description": spec["description"], "category": category,
         "split": split, "difficulty": spec["difficulty"]}
        for category, spec in _SPECS.items() for split in ("dev", "holdout")
    ]


def _metadata(task_id: str) -> dict[str, Any]:
    for task in list_tasks():
        if task["id"] == task_id:
            return task
    raise ValueError(f"Unknown task {task_id!r}; use list_tasks() for valid IDs")


def _data(split: str) -> dict[str, list[dict[str, Any]]]:
    """Fixed, independently regenerated source data, with deliberately hard edges."""
    rng = random.Random(72831 if split == "dev" else 992873)
    prefix = "D" if split == "dev" else "H"
    customers = [{"customer_id": f"{prefix}C{i:03}", "person_id": f"{prefix}P{i // 2:03}"} for i in range(20)]
    orders, items, payments, refunds, events = [], [], [], [], []
    times = ["2026-06-01 15:59:59", "2026-06-01 16:00:00", "2026-06-01 23:59:59", "2026-06-02 00:00:00", "2026-06-30 16:00:00", "2026-12-31 16:00:00"]
    count = 36 if split == "dev" else 53
    for i in range(count):
        oid = f"{prefix}O{i:03}"
        status = "cancelled" if i % 9 == 8 else "completed"
        timestamp = times[i] if i < len(times) else (datetime(2026, 6, 1) + timedelta(days=rng.randrange(7), seconds=rng.randrange(86400))).isoformat(sep=" ")
        orders.append({"order_id": oid, "customer_id": customers[i % len(customers)]["customer_id"], "ordered_at": timestamp, "status": status})
        gross = 0
        for j in range(1 + i % 3):
            qty = rng.randint(1, 4)
            # Both accounts of the first person have only zero-value orders.
            price = 0 if i % len(customers) in (0, 1) else rng.choice([99, 125, 499, 1000, 2599, 10437])
            items.append({"order_id": oid, "line_id": f"{oid}L{j}", "quantity": qty, "unit_price_cents": price})
            gross += qty * price
        n_payments = 1 + (i + 1) % 3
        remaining = gross
        for j in range(n_payments):
            amount = remaining if j == n_payments - 1 else remaining // (n_payments - j)
            payments.append({"order_id": oid, "payment_id": f"{oid}P{j}", "amount_cents": amount})
            remaining -= amount
        if i % 4 == 0 or status == "cancelled":
            requested = 0 if i == 0 else gross // 2
            paid = 0 if i % 8 == 0 else requested
            refunds.append({"refund_id": f"{oid}R0", "order_id": oid, "requested_cents": requested, "paid_cents": paid, "status": "pending" if paid == 0 else "paid"})
            if i % 12 == 0 and gross:
                refunds.append({"refund_id": f"{oid}R1", "order_id": oid, "requested_cents": gross // 5, "paid_cents": gross // 5, "status": "paid"})
        events.append({"event_id": i * 3, "order_id": oid, "updated_at": "2026-07-01 00:00:00", "status": "placed", "net_cents": gross})
        events.append({"event_id": i * 3 + 1, "order_id": oid, "updated_at": "2026-07-02 00:00:00", "status": status, "net_cents": gross if status == "completed" else 0})
        if i % 5 == 0:
            # Equal timestamp: the event ID is the defined deterministic tie-break.
            events.append({"event_id": i * 3 + 2, "order_id": oid, "updated_at": "2026-07-02 00:00:00", "status": "refunded", "net_cents": 0})
    # Physical file order must not accidentally give away latest-event selection.
    rng.shuffle(events)
    return {"customers": customers, "orders": orders, "order_items": items, "payments": payments, "refunds": refunds, "order_events": events}


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _buggy_sql(category: str) -> str:
    return {
        "revenue_fanout": """{{ config(materialized='table') }}
select o.order_id, sum(i.quantity * i.unit_price_cents)::bigint as gross_cents,
       sum(p.amount_cents)::bigint as paid_cents
from {{ ref('orders') }} o
join {{ ref('order_items') }} i on o.order_id = i.order_id
join {{ ref('payments') }} p on o.order_id = p.order_id
where o.status = 'completed' group by o.order_id
""",
        "refund_reconciliation": """{{ config(materialized='table') }}
select r.refund_id, r.order_id, r.requested_cents, r.paid_cents,
       r.paid_cents::double / r.requested_cents as completion_ratio
from {{ ref('refunds') }} r join {{ ref('orders') }} o using(order_id)
where o.status = 'completed'
""",
        "local_day_boundary": """{{ config(materialized='table') }}
with totals as (
 select order_id, sum(quantity * unit_price_cents)::bigint as gross_cents
 from {{ ref('order_items') }} group by order_id
)
select cast(o.ordered_at as date) as business_day, count(*)::bigint as order_count,
       sum(t.gross_cents)::bigint as gross_cents
from {{ ref('orders') }} o join totals t using(order_id)
where o.status = 'completed' group by 1
""",
        "repeat_customer_identity": """{{ config(materialized='table') }}
with totals as (
 select order_id, sum(quantity * unit_price_cents)::bigint as gross_cents
 from {{ ref('order_items') }} group by order_id
)
select min(c.person_id) as person_id, count(*)::bigint as order_count,
       sum(t.gross_cents)::bigint as gross_cents,
       case when count(*) >= 2 then 1 else 0 end as is_repeat
from {{ ref('orders') }} o join {{ ref('customers') }} c using(customer_id)
join totals t using(order_id) where o.status = 'completed'
group by c.customer_id
""",
        "incremental_replay": """{{ config(materialized='incremental', incremental_strategy='append') }}
select order_id, status, net_cents from (
 select *, row_number() over(partition by order_id order by updated_at desc, event_id desc) as rn
 from {{ ref('order_events') }}
) where rn = 1
""",
        "build_customer_ltv": """{{ config(materialized='table') }}
-- TODO: implement the finance team's documented customer-level mart.
select cast(null as varchar) as person_id, cast(0 as bigint) as order_count,
       cast(0 as bigint) as gross_cents, cast(0 as bigint) as refund_cents,
       cast(0 as bigint) as net_cents where false
""",
    }[category]


def _visible_checks(category: str, output: str) -> dict[str, str]:
    key = "person_id" if category in ("repeat_customer_identity", "build_customer_ltv") else "business_day" if category == "local_day_boundary" else "refund_id" if category == "refund_reconciliation" else "order_id"
    checks = {"output_key": f"select {key} from {{{{ ref('{output}') }}}} group by {key} having count(*) <> 1 or {key} is null\n"}
    if category == "revenue_fanout":
        checks["payment_item_reconciliation"] = f"""select order_id from {{{{ ref('{output}') }}}}
where gross_cents <> paid_cents
union all
select '__total__' where
 (select sum(gross_cents) from {{{{ ref('{output}') }}}}) <>
 (select sum(i.quantity * i.unit_price_cents) from {{{{ ref('order_items') }}}} i
 join {{{{ ref('orders') }}}} o using(order_id) where o.status='completed')
"""
    elif category == "refund_reconciliation":
        checks["coverage_and_finite_ratios"] = f"""select refund_id from {{{{ ref('{output}') }}}}
where completion_ratio is null or not isfinite(completion_ratio)
union all
select r.refund_id from {{{{ ref('refunds') }}}} r
left join {{{{ ref('{output}') }}}} x using(refund_id) where x.refund_id is null
"""
    elif category == "local_day_boundary":
        checks["business_day_coverage"] = f"""select distinct cast(cast(ordered_at as timestamp) + interval '8 hours' as date) as missing_day
from {{{{ ref('orders') }}}} where status='completed'
except select business_day from {{{{ ref('{output}') }}}}
"""
    elif category == "repeat_customer_identity":
        checks["customer_order_conservation"] = f"""select 'order_count' as problem where
(select sum(order_count) from {{{{ ref('{output}') }}}}) <>
(select count(*) from {{{{ ref('orders') }}}} where status='completed')
"""
    elif category == "build_customer_ltv":
        checks["population_and_accounting"] = f"""select 'empty' as problem where not exists(select 1 from {{{{ ref('{output}') }}}})
union all select person_id from {{{{ ref('{output}') }}}} where net_cents <> gross_cents-refund_cents
"""
    return checks


def create_task(task_id: str, workspace: Path) -> dict[str, Any]:
    """Create a fresh dbt project. Refuse to overwrite an existing project."""
    meta = _metadata(task_id)
    spec = _SPECS[meta["category"]]
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if (workspace / "dbt_project.yml").exists():
        raise FileExistsError(f"Task workspace already contains a dbt project: {workspace}")
    for folder in ("seeds", "models/marts", "checks"):
        (workspace / folder).mkdir(parents=True, exist_ok=True)
    for table, rows in _data(meta["split"]).items():
        (workspace / "seeds" / f"{table}.csv").write_bytes(_csv_bytes(rows))
    database = workspace / "warehouse.duckdb"
    # Absolute paths work both with and without DBT_WORKSPACE and avoid relying on
    # the launcher's current working directory for database location.
    db_path = str(database).replace("\\", "/").replace("'", "''")
    (workspace / "dbt_project.yml").write_text("name: datapatch_task\nversion: '1.0.0'\nconfig-version: 2\nprofile: datapatch_task\nmodel-paths: ['models']\nseed-paths: ['seeds']\ntest-paths: ['checks']\nmodels:\n  datapatch_task:\n    +materialized: table\n", encoding="utf-8")
    (workspace / "profiles.yml").write_text(f"datapatch_task:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n      path: '{db_path}'\n      schema: main\n      threads: 1\n", encoding="utf-8")
    (workspace / "models/marts" / f"{spec['output']}.sql").write_text(_buggy_sql(meta["category"]), encoding="utf-8")
    for name, sql in _visible_checks(meta["category"], spec["output"]).items():
        (workspace / "checks" / f"{name}.sql").write_text(sql, encoding="utf-8")
    (workspace / "README.md").write_text(
        f"# {meta['title']}\n\n{meta['description']}\n\n## Output contract\n\n"
        f"Table: `{spec['output']}`\n\nColumns (in order): {', '.join(spec['columns'])}.\n\n{spec['contract']}\n\n"
        "## Environment and allowed changes\n\n"
        "This is a synthetic, local retail fixture. Amounts are integer cents. Inspect seeds, schema, model SQL, and visible checks as needed. Modify models or add macros; do not modify seeds, profiles, checks, the documented output contract, or disable tests.\n\n"
        "Run `dbt seed --project-dir . --profiles-dir .`, then `dbt run --project-dir . --profiles-dir .`, then `dbt test --project-dir . --profiles-dir .`.\n\n"
        "The database path in profiles.yml is absolute. Run one dbt process at a time. Visible tests are partial invariants; passing them does not prove full correctness. The evaluator compares all output rows against a separately implemented Python reference outside this workspace.\n",
        encoding="utf-8",
    )
    # The public business contracts declare these output grains explicitly.
    # Do not infer a key from current data uniqueness or from evaluator rows.
    output_keys = {
        "order_revenue": ["order_id"], "refund_reconciliation": ["refund_id"],
        "daily_sales": ["business_day"], "customer_repeat": ["person_id"],
        "order_state": ["order_id"], "customer_ltv": ["person_id"],
    }
    return {**meta, "metadata": meta, "output_table": spec["output"], "key_columns": output_keys[spec["output"]], "database_path": str(database), "expected_columns": list(spec["columns"])}


def _oracle(category: str, data: dict[str, list[dict[str, Any]]]) -> list[tuple[Any, ...]]:
    """Independent Python computations: no SQL, no model output, no workspace reads."""
    orders = {row["order_id"]: row for row in data["orders"]}
    people = {row["customer_id"]: row["person_id"] for row in data["customers"]}
    item_totals = {oid: 0 for oid in orders}
    paid_totals = {oid: 0 for oid in orders}
    refunds = {oid: 0 for oid in orders}
    for row in data["order_items"]:
        item_totals[row["order_id"]] += row["quantity"] * row["unit_price_cents"]
    for row in data["payments"]:
        paid_totals[row["order_id"]] += row["amount_cents"]
    for row in data["refunds"]:
        refunds[row["order_id"]] += row["paid_cents"]
    completed = [row for row in data["orders"] if row["status"] == "completed"]
    if category == "revenue_fanout":
        return [(o["order_id"], item_totals[o["order_id"]], paid_totals[o["order_id"]]) for o in completed]
    if category == "refund_reconciliation":
        return [(r["refund_id"], r["order_id"], r["requested_cents"], r["paid_cents"], r["paid_cents"] / r["requested_cents"] if r["requested_cents"] > 0 else 0.0) for r in data["refunds"]]
    if category == "local_day_boundary":
        days: dict[str, list[int]] = {}
        for o in completed:
            day = (datetime.fromisoformat(o["ordered_at"]) + timedelta(hours=8)).date().isoformat()
            acc = days.setdefault(day, [0, 0])
            acc[0] += 1
            acc[1] += item_totals[o["order_id"]]
        return [(day, *values) for day, values in days.items()]
    if category in ("repeat_customer_identity", "build_customer_ltv"):
        totals: dict[str, list[int]] = {}
        for o in completed:
            acc = totals.setdefault(people[o["customer_id"]], [0, 0, 0])
            acc[0] += 1
            acc[1] += item_totals[o["order_id"]]
            acc[2] += refunds[o["order_id"]]
        if category == "repeat_customer_identity":
            return [(person, values[0], values[1], int(values[0] >= 2)) for person, values in totals.items()]
        return [(person, *values, values[1] - values[2]) for person, values in totals.items()]
    if category == "incremental_replay":
        newest: dict[str, dict[str, Any]] = {}
        for event in data["order_events"]:
            prev = newest.get(event["order_id"])
            if prev is None or (event["updated_at"], event["event_id"]) > (prev["updated_at"], prev["event_id"]):
                newest[event["order_id"]] = event
        return [(oid, event["status"], event["net_cents"]) for oid, event in newest.items()]
    raise ValueError(category)


def _rows_equal(expected: list[tuple[Any, ...]], actual: list[tuple[Any, ...]]) -> tuple[bool, list[dict[str, Any]]]:
    def sort_key(row: tuple[Any, ...]) -> tuple[str, ...]:
        return tuple(str(value) for value in row)
    mismatches = []
    for index, (exp, act) in enumerate(zip(sorted(expected, key=sort_key), sorted(actual, key=sort_key))):
        normal = tuple(value.isoformat() if hasattr(value, "isoformat") else value for value in act)
        equal = len(exp) == len(normal)
        for left, right in zip(exp, normal):
            if isinstance(left, float):
                equal = equal and isinstance(right, (int, float, Decimal)) and math.isfinite(float(right)) and math.isclose(left, float(right), rel_tol=1e-9, abs_tol=1e-9)
            elif isinstance(left, int):
                equal = equal and right is not None and right == left
            else:
                equal = equal and right == left
        if not equal and len(mismatches) < 5:
            # Failed candidates can contain NaN/Inf; keep evaluator reports valid
            # JSON (strict HTTP serializers reject non-finite numeric literals).
            safe_actual = [str(v) if (isinstance(v, float) and not math.isfinite(v)) or not isinstance(v, (int, float, str, type(None))) else v for v in normal]
            mismatches.append({"row": index, "expected": list(exp), "actual": safe_actual})
    return len(expected) == len(actual) and not mismatches, mismatches


def _read_output(workspace: Path, table: str, columns: list[str]) -> tuple[list[str], list[tuple[Any, ...]]]:
    import duckdb
    with duckdb.connect(str(workspace / "warehouse.duckdb"), read_only=True) as connection:
        description = connection.execute(f'SELECT * FROM main."{table}" LIMIT 0').description
        actual_columns = [entry[0] for entry in description]
        selected = ", ".join(f'"{name}"' for name in columns)
        rows = connection.execute(f'SELECT {selected} FROM main."{table}"').fetchall()
    return actual_columns, rows


def _replay_incremental(workspace: Path, table: str) -> dict[str, Any]:
    executable = Path(sys.executable).with_name("dbt.exe" if os.name == "nt" else "dbt")
    command = str(executable) if executable.exists() else shutil.which("dbt")
    if not command:
        return {"passed": False, "details": "dbt executable unavailable; incremental replay was not verified"}
    try:
        result = subprocess.run([command, "run", "--select", table, "--project-dir", str(workspace), "--profiles-dir", str(workspace), "--quiet"], cwd=workspace, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        return {"passed": result.returncode == 0, "details": (result.stdout + result.stderr)[-1500:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"passed": False, "details": str(exc)}


def verify_task(task_id: str, workspace: Path) -> dict[str, Any]:
    """Grade every row against regenerated data, outside the agent environment.

    Incremental tasks also rerun the model once. This intentionally changes the
    candidate database to expose duplicate-on-replay defects. Never register this
    function as an agent tool: expected values are evaluator-only evidence.
    """
    meta = _metadata(task_id)
    spec = _SPECS[meta["category"]]
    workspace = Path(workspace).resolve()
    data = _data(meta["split"])
    expected = _oracle(meta["category"], data)
    checks: list[dict[str, Any]] = []
    altered = [name for name, rows in data.items() if not (workspace / "seeds" / f"{name}.csv").exists() or hashlib.sha256((workspace / "seeds" / f"{name}.csv").read_bytes()).digest() != hashlib.sha256(_csv_bytes(rows)).digest()]
    checks.append({"name": "source_integrity", "passed": not altered, "expected": "original immutable source CSVs", "actual": altered or "unchanged"})
    try:
        columns, actual = _read_output(workspace, spec["output"], spec["columns"])
        checks.append({"name": "output_columns", "passed": columns == spec["columns"], "expected": spec["columns"], "actual": columns})
        checks.append({"name": "row_count", "passed": len(actual) == len(expected), "expected": len(expected), "actual": len(actual)})
        same, differences = _rows_equal(expected, actual)
        checks.append({"name": "all_row_values", "passed": same, "expected": "Python oracle, every row", "actual": differences or "all rows match"})
        if meta["category"] == "incremental_replay":
            # Enforce the explicit engineering constraint, as well as data output.
            import json
            manifest = json.loads((workspace / "target/manifest.json").read_text(encoding="utf-8"))
            matching_nodes = [node for node in manifest["nodes"].values() if node.get("resource_type") == "model" and node.get("alias") == spec["output"]]
            incremental = len(matching_nodes) == 1 and matching_nodes[0].get("config", {}).get("materialized") == "incremental"
            checks.append({"name": "incremental_materialization", "passed": incremental, "expected": "incremental model retained", "actual": incremental})
            replay = _replay_incremental(workspace, spec["output"])
            checks.append({"name": "replay_run", "passed": replay["passed"], "expected": "dbt rerun succeeds", "actual": replay["details"] or "succeeded"})
            if replay["passed"]:
                _, replayed = _read_output(workspace, spec["output"], spec["columns"])
                replay_same, replay_differences = _rows_equal(expected, replayed)
                checks.append({"name": "replay_idempotency", "passed": replay_same, "expected": {"rows": len(expected), "values": "unchanged oracle"}, "actual": {"rows": len(replayed), "differences": replay_differences}})
    except Exception as exc:
        checks.append({"name": "output_readable", "passed": False, "expected": f"readable {spec['output']} with required columns", "actual": str(exc)[:1500]})
    passed = all(check["passed"] for check in checks)
    failures = [check["name"] for check in checks if not check["passed"]]
    return {"passed": passed, "checks": checks, "summary": "All independent checks passed" if passed else "Failed: " + ", ".join(failures)}
