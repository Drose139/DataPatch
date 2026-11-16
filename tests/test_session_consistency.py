"""Exercise UTC query/context sessions with real DuckDB and a controlled host clock."""
import hashlib

import duckdb
import pytest

from datapatch.context import build_task_context
from datapatch.workspace import Workspace


@pytest.fixture
def host_clock_database(tmp_path, monkeypatch):
    database = tmp_path / "warehouse.duckdb"
    original_connect = duckdb.connect
    with original_connect(str(database)) as connection:
        connection.execute("CREATE TABLE stg_clock_parent(session_id VARCHAR)")
        connection.execute("INSERT INTO stg_clock_parent VALUES ('1970-01-01 00:00:00+00')")
        connection.execute("CREATE VIEW stg_clock_child AS SELECT CAST(to_timestamp(0) AS VARCHAR) AS session_id FROM range(2)")
    (tmp_path / "models/staging").mkdir(parents=True)
    for name in ("stg_clock_parent", "stg_clock_child"):
        (tmp_path / "models/staging" / (name + ".sql")).write_text("select 1 as session_id", encoding="utf-8")
    (tmp_path / "models/report.sql").write_text(
        "select * from {{ ref('stg_clock_parent') }} p left join {{ ref('stg_clock_child') }} c using(session_id)", encoding="utf-8")
    observed_sessions = []

    class ObservedConnection:
        def __init__(self, connection):
            self.connection = connection
        def __getattr__(self, name):
            return getattr(self.connection, name)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            observed_sessions.append(self.connection.execute("SELECT current_setting('TimeZone')").fetchone()[0])
            self.connection.close()

    def host_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        # Control the inherited session in this test rather than relying on
        # the operating system timezone; every query still uses real DuckDB.
        connection.execute("SET TimeZone='Asia/Shanghai'")
        return ObservedConnection(connection)

    monkeypatch.setattr(duckdb, "connect", host_connect)
    return tmp_path, database, observed_sessions


def test_utc_tools_match_epoch_semantics_and_default_keeps_host_clock(host_clock_database):
    root, database, observed = host_clock_database
    query = "SELECT current_setting('TimeZone'), epoch(CAST(TIMESTAMP '1970-01-01 00:00:00' AS TIMESTAMPTZ)), CAST(to_timestamp(0) AS TIMESTAMP)"
    default = Workspace(root, database_path=database)
    utc = Workspace(root, database_path=database, duckdb_timezone="UTC")
    assert default.query_sql(query)["rows"] == [["Asia/Shanghai", -28800.0, "1970-01-01 08:00:00"]]
    assert utc.query_sql(query)["rows"] == [["UTC", 0.0, "1970-01-01 00:00:00"]]
    assert utc.search_schema("clock")["tables"]
    assert observed[-1] == "UTC"
    assert default.search_schema("clock")["tables"]
    assert observed[-1] == "Asia/Shanghai"


def test_utc_setting_does_not_enable_agent_set_or_database_writes(host_clock_database):
    root, database, _ = host_clock_database
    workspace = Workspace(root, database_path=database, duckdb_timezone="UTC")
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    for statement in ("SET TimeZone='Asia/Shanghai'", "DELETE FROM stg_clock_parent", "SELECT 1; SET TimeZone='UTC'"):
        with pytest.raises(ValueError, match="SELECT/WITH"):
            workspace.query_sql(statement)
    assert workspace.query_sql("SELECT COUNT(*) FROM stg_clock_parent")["rows"] == [[1]]
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("create_target", [False, True])
def test_context_schema_and_relationships_share_workspace_session(host_clock_database, create_target):
    root, database, observed = host_clock_database
    if create_target:
        instruction = "Create a model called new_report. Explore staging tables for clock_parent and clock_child."
        focus = "new_report"
    else:
        instruction = "Repair models/report.sql without losing clock relationships."
        focus = "report"
    default = build_task_context(Workspace(root, database_path=database), instruction, focus)
    assert default["schema"]["tables"]
    assert default["relationship_checks"]["relationships"][0]["unmatched_non_null_rows"] == 2
    assert observed[-2:] == ["Asia/Shanghai", "Asia/Shanghai"]
    utc = build_task_context(Workspace(root, database_path=database, duckdb_timezone="UTC"), instruction, focus)
    assert utc["schema"]["tables"]
    assert utc["relationship_checks"]["relationships"][0]["unmatched_non_null_rows"] == 0
    assert observed[-2:] == ["UTC", "UTC"]
    assert utc["metadata"]["runtime_settings"] == {"duckdb_timezone": "UTC"}


@pytest.mark.parametrize("timezone", ["Asia/Shanghai", "UTC; DROP TABLE x"])
def test_workspace_rejects_unconfigured_timezone(tmp_path, timezone):
    with pytest.raises(ValueError, match="UTC or omitted"):
        Workspace(tmp_path, duckdb_timezone=timezone)
