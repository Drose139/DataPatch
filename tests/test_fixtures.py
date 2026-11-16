"""Execution tests for fixture grading; reference repairs are test-only assets.

These statements are never copied into agent workspaces by create_task(). They
independently express the business contracts to catch a broken fixture/oracle.
"""
from pathlib import Path
import subprocess
import sys

import pytest

from datapatch.fixtures import create_task, list_tasks, verify_task


_REPAIRS = {
    "revenue_fanout": """
{{ config(materialized='table') }}
with item_sum as (
 select order_id, sum(quantity*unit_price_cents)::bigint gross_cents
 from {{ ref('order_items') }} group by order_id
), pay_sum as (
 select order_id, sum(amount_cents)::bigint paid_cents
 from {{ ref('payments') }} group by order_id
)
select o.order_id, i.gross_cents, p.paid_cents
from {{ ref('orders') }} o join item_sum i using(order_id)
join pay_sum p using(order_id) where o.status='completed'
""",
    "refund_reconciliation": """
{{ config(materialized='table') }}
select refund_id, order_id, requested_cents, paid_cents,
 case when requested_cents > 0 then paid_cents::double/requested_cents else 0.0 end completion_ratio
from {{ ref('refunds') }}
""",
    "local_day_boundary": """
{{ config(materialized='table') }}
with item_sum as (
 select order_id, sum(quantity*unit_price_cents)::bigint gross_cents
 from {{ ref('order_items') }} group by order_id
)
select cast(cast(ordered_at as timestamp)+interval '8 hours' as date) business_day,
 count(*)::bigint order_count, sum(i.gross_cents)::bigint gross_cents
from {{ ref('orders') }} o join item_sum i using(order_id)
where status='completed' group by 1
""",
    "repeat_customer_identity": """
{{ config(materialized='table') }}
with item_sum as (
 select order_id, sum(quantity*unit_price_cents)::bigint gross_cents
 from {{ ref('order_items') }} group by order_id
)
select c.person_id, count(*)::bigint order_count, sum(i.gross_cents)::bigint gross_cents,
 cast(count(*)>=2 as integer) is_repeat
from {{ ref('orders') }} o join {{ ref('customers') }} c using(customer_id)
join item_sum i using(order_id) where status='completed' group by c.person_id
""",
    "incremental_replay": """
{{ config(materialized='incremental', incremental_strategy='delete+insert', unique_key='order_id') }}
select order_id, status, net_cents from {{ ref('order_events') }}
qualify row_number() over(partition by order_id order by updated_at desc, event_id desc)=1
""",
    "build_customer_ltv": """
{{ config(materialized='table') }}
with item_sum as (
 select order_id, sum(quantity*unit_price_cents)::bigint gross_cents
 from {{ ref('order_items') }} group by order_id
), refund_sum as (
 select order_id, sum(paid_cents)::bigint refund_cents
 from {{ ref('refunds') }} group by order_id
)
select c.person_id, count(*)::bigint order_count, sum(i.gross_cents)::bigint gross_cents,
 sum(coalesce(r.refund_cents,0))::bigint refund_cents,
 (sum(i.gross_cents)-sum(coalesce(r.refund_cents,0)))::bigint net_cents
from {{ ref('orders') }} o join {{ ref('customers') }} c using(customer_id)
join item_sum i using(order_id) left join refund_sum r using(order_id)
where o.status='completed' group by c.person_id
""",
}


def _dbt(workspace: Path, *arguments: str, expect_success: bool = True):
    # dbt's DuckDB adapter retains process-global connections. Use a child process
    # to match production and let the independent evaluator open a fresh reader.
    result = subprocess.run([sys.executable, "-m", "datapatch.dbt_runner", "--project", str(workspace), *arguments], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert (result.returncode == 0) == expect_success, result.stdout + result.stderr
    return result


def test_task_catalog_and_reproducible_split(tmp_path):
    tasks = list_tasks()
    assert len(tasks) == 12
    assert len({task["id"] for task in tasks}) == 12
    assert {task["split"] for task in tasks} == {"dev", "holdout"}
    for split in ("dev", "holdout"):
        first, second = tmp_path / (split + "1"), tmp_path / (split + "2")
        create_task("revenue_fanout_" + split, first)
        create_task("revenue_fanout_" + split, second)
        assert (first / "seeds/orders.csv").read_bytes() == (second / "seeds/orders.csv").read_bytes()
    assert (tmp_path / "dev1/seeds/orders.csv").read_bytes() != (tmp_path / "holdout1/seeds/orders.csv").read_bytes()
    with pytest.raises(FileExistsError):
        create_task("revenue_fanout_dev", tmp_path / "dev1")
    with pytest.raises(ValueError):
        create_task("does-not-exist", tmp_path / "invalid")


@pytest.mark.parametrize("task", list_tasks(), ids=lambda task: task["id"])
def test_initial_defect_and_independent_repair(task, tmp_path):
    """All 12 compile/run; all fail gold; genuine SQL repairs pass all rows."""
    workspace = tmp_path / task["id"]
    meta = create_task(task["id"], workspace)
    _dbt(workspace, "seed")
    _dbt(workspace, "run")
    before = verify_task(task["id"], workspace)
    assert not before["passed"], before
    assert not any(check["name"] == "output_readable" and not check["passed"] for check in before["checks"]), before
    if task["category"] == "incremental_replay":
        assert any(check["name"] == "replay_idempotency" and not check["passed"] for check in before["checks"]), before
    # Initial visible invariants must actually expose a defect as well. For the
    # incremental family, verify_task has just performed the revealing replay.
    _dbt(workspace, "test", expect_success=False)
    # These fixes exist only in this test module, outside generated workspaces.
    model = workspace / "models/marts" / (meta["output_table"] + ".sql")
    model.write_text(_REPAIRS[task["category"]], encoding="utf-8")
    _dbt(workspace, "run", "--full-refresh")
    after = verify_task(task["id"], workspace)
    assert after["passed"], after
    _dbt(workspace, "test")


def test_source_tampering_fails_even_with_correct_output(tmp_path):
    workspace = tmp_path / "tampered"
    meta = create_task("refund_reconciliation_dev", workspace)
    (workspace / "models/marts" / (meta["output_table"] + ".sql")).write_text(_REPAIRS["refund_reconciliation"], encoding="utf-8")
    _dbt(workspace, "seed")
    _dbt(workspace, "run")
    assert verify_task("refund_reconciliation_dev", workspace)["passed"]
    with (workspace / "seeds/refunds.csv").open("a", encoding="utf-8") as stream:
        stream.write("\n")
    result = verify_task("refund_reconciliation_dev", workspace)
    assert not result["passed"]
    assert not result["checks"][0]["passed"]
