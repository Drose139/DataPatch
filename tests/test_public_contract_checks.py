"""Execute the shipped public contract SQL against miniature DuckDB facts.

These are project business checks, not benchmark verifier tests. No dbt or model
provider runs; the actual Workspace query/Jinja/check path reads a temporary DB.
"""
from pathlib import Path
import shutil

import duckdb
import pytest

from datapatch.workspace import Workspace


CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "examples/public_contracts/product"


@pytest.fixture
def contract_workspace(tmp_path):
    checks = tmp_path / "checks"
    checks.mkdir()
    for source in CONTRACT_ROOT.glob("*.sql"):
        shutil.copyfile(source, checks / source.name)
    database = tmp_path / "miniature.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("""
            CREATE TABLE stg_product__products(product_id INTEGER);
            INSERT INTO stg_product__products VALUES (1), (2), (3);
            CREATE TABLE stg_orders__orders(order_id INTEGER, status VARCHAR);
            INSERT INTO stg_orders__orders VALUES
                (1, 'COMPLETED'), (2, 'SHIPPED'), (3, 'CANCELLED'),
                (4, 'RETURNED'), (5, 'FAILED');
            CREATE TABLE stg_orders__order_lines(
                order_id INTEGER, quantity_ordered DOUBLE, line_total DOUBLE);
            INSERT INTO stg_orders__order_lines VALUES
                (1, 2, 18), (1, 1, 12), (2, 3, 45),
                (3, 100, 999), (4, 100, 999), (5, 100, 999);
            CREATE TABLE fct_product_metrics(
                product_id INTEGER, units_sold DOUBLE,
                product_revenue DOUBLE, avg_unit_price DOUBLE);
            INSERT INTO fct_product_metrics VALUES
                (1, 3, 30, 10), (2, 3, 45, 15), (3, 0, 0, 0);
        """)
    return Workspace(tmp_path, database_path=database)


def execute_checks(workspace):
    result = workspace.check_contracts()
    assert result["available"] is True
    assert {row["name"] for row in result["checks"]} == {
        "product_coverage", "sales_totals", "weighted_price"
    }
    assert not any("error" in row for row in result["checks"]), result
    return result


def test_correct_product_output_passes_actual_workspace_contracts(contract_workspace):
    result = execute_checks(contract_workspace)
    assert result["passed"] is True
    assert all(not row["violations"] for row in result["checks"])


def test_zero_unit_product_may_have_undefined_price(contract_workspace):
    with duckdb.connect(str(contract_workspace.database_path)) as connection:
        connection.execute("UPDATE fct_product_metrics SET avg_unit_price=NULL WHERE product_id=3")
    assert execute_checks(contract_workspace)["passed"] is True


@pytest.mark.parametrize("mutation,failed_check", [
    ("UPDATE fct_product_metrics SET product_revenue=36, avg_unit_price=12 WHERE product_id=1", "sales_totals"),
    ("UPDATE fct_product_metrics SET units_sold=0, product_revenue=0, avg_unit_price=0 WHERE product_id=2", "sales_totals"),
    ("INSERT INTO fct_product_metrics VALUES (3,0,0,0)", "product_coverage"),
    ("DELETE FROM fct_product_metrics WHERE product_id=3", "product_coverage"),
    ("UPDATE fct_product_metrics SET avg_unit_price=10.5 WHERE product_id=1", "weighted_price"),
    ("UPDATE fct_product_metrics SET avg_unit_price=NULL WHERE product_id=1", "weighted_price"),
    # NULL on an unsold product does not change SUMs: a row-level check must
    # reject it instead of relying on NULL comparisons in a WHERE clause.
    ("UPDATE fct_product_metrics SET units_sold=NULL WHERE product_id=3", "weighted_price"),
    ("UPDATE fct_product_metrics SET product_revenue=NULL WHERE product_id=3", "weighted_price"),
    ("UPDATE fct_product_metrics SET units_sold=NULL WHERE product_id=1", "weighted_price"),
    ("UPDATE fct_product_metrics SET product_revenue=NULL WHERE product_id=1", "weighted_price"),
])
def test_business_counterexamples_are_rejected(contract_workspace, mutation, failed_check):
    with duckdb.connect(str(contract_workspace.database_path)) as connection:
        connection.execute(mutation)
    result = execute_checks(contract_workspace)
    failed = {row["name"]: row for row in result["checks"] if not row["passed"]}
    assert result["passed"] is False
    assert failed_check in failed
    assert failed[failed_check]["violations"]
