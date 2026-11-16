from pathlib import Path

import duckdb
import pytest

from datapatch.workspace import Workspace


@pytest.fixture
def workspace(tmp_path: Path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "report.sql").write_text("select * from {{ ref('raw_orders') }}\n", encoding="utf-8")
    (tmp_path / "checks").mkdir()
    (tmp_path / "checks" / "no_negative.sql").write_text("select * from {{ ref('report') }} where amount < 0", encoding="utf-8")
    with duckdb.connect(str(tmp_path / "warehouse.duckdb")) as connection:
        connection.execute("create table report as select 1 id, -20 amount")
    return Workspace(tmp_path)


def test_invariant_returns_counterexample_and_resolves_ref(workspace):
    result = workspace.check_contracts()
    assert result["passed"] is False
    assert result["checks"][0]["violations"] == [[1, -20]]


def test_tools_cannot_edit_sources_or_escape_workspace(workspace):
    with pytest.raises(ValueError):
        workspace.write_model("../escape.sql", "select 1")
    with pytest.raises(ValueError):
        workspace.write_model("checks/no_negative.sql", "select 1 where false")
    with pytest.raises(ValueError):
        workspace.query_sql("delete from report")


def test_query_cannot_read_host_files(workspace):
    with pytest.raises(duckdb.Error):
        workspace.query_sql("select * from read_csv('C:/outside.csv')")


def test_diff_and_lineage_record_source_changes(workspace):
    assert workspace.get_lineage()["nodes"][0]["upstream"] == ["raw_orders"]
    workspace.write_model("models/report.sql", "select 1 as id, 20 as amount\n")
    assert "+select 1 as id, 20 as amount" in workspace.diff()
