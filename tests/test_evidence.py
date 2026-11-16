import json

import duckdb
import pytest

from datapatch.evidence import capture_output, compare_outputs


def _database(tmp_path, sql):
    path = tmp_path / "evidence.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute(sql)
    return path


def test_keyed_change_add_remove_and_unchanged_are_separate(tmp_path):
    path = _database(tmp_path, "create table result(id int, amount int); insert into result values (1,10),(2,20),(3,30)")
    before = capture_output(path, "main.result", ["id"])
    with duckdb.connect(str(path)) as connection:
        connection.execute("update result set amount=21 where id=2; delete from result where id=3; insert into result values(4,40)")
    after = capture_output(path, "main.result", ["id"])
    comparison = compare_outputs(before, after)
    assert comparison["counts"] == {"before": 3, "after": 3, "delta": 0}
    diff = comparison["keyed_diff"]
    assert diff["supported"]
    assert [diff[name] for name in ("added_count", "removed_count", "changed_count", "unchanged_count")] == [1, 1, 1, 1]
    assert diff["samples"]["added"] == [{"id": 4, "amount": 40}]
    assert diff["samples"]["removed"] == [{"id": 3, "amount": 30}]
    assert diff["samples"]["changed"][0] == {"key": {"id": 2}, "before": {"id": 2, "amount": 20}, "after": {"id": 2, "amount": 21}, "changed_columns": ["amount"]}


@pytest.mark.parametrize("values,status", [("(1,10),(1,20)", "duplicate_keys"), ("(null,10),(2,20)", "null_keys")])
def test_invalid_keys_disable_full_keyed_diff(tmp_path, values, status):
    path = _database(tmp_path, f"create table result(id int,amount int);insert into result values {values}")
    snapshot = capture_output(path, "result", ["id"])
    assert not snapshot["key_valid"]
    assert snapshot["key_validation"]["status"] == status
    comparison = compare_outputs(snapshot, snapshot)
    assert not comparison["keyed_diff"]["supported"]
    assert comparison["keyed_diff"]["changed_count"] is None
    assert compare_outputs(capture_output(path, "result"), snapshot)["keyed_diff"]["reason"] == "key_not_declared"
    assert capture_output(path, "result", ["missing"])["key_validation"]["status"] == "missing_columns"


def test_schema_changes_are_not_misreported_as_changed_values(tmp_path):
    path = _database(tmp_path, "create table result(id int,amount int,legacy varchar);insert into result values(1,10,'old')")
    before = capture_output(path, "result", ["id"])
    with duckdb.connect(str(path)) as connection:
        connection.execute("alter table result drop column legacy; alter table result alter column amount type bigint; alter table result add column tier varchar")
    comparison = compare_outputs(before, capture_output(path, "result", ["id"]))
    assert comparison["schema"]["added"] == [{"name": "tier", "type": "VARCHAR"}]
    assert comparison["schema"]["removed"] == [{"name": "legacy", "type": "VARCHAR"}]
    assert comparison["schema"]["type_changed"] == [{"name": "amount", "before": "INTEGER", "after": "BIGINT"}]
    assert comparison["keyed_diff"]["changed_count"] == 0
    assert comparison["keyed_diff"]["unchanged_count"] == 1


def test_missing_baseline_does_not_claim_zero_changes(tmp_path):
    path = _database(tmp_path, "create table result(id int); insert into result values(1)")
    missing = capture_output(path, "does_not_exist", ["id"])
    after = capture_output(path, "result", ["id"])
    assert not missing["available"] and missing["error"]
    comparison = compare_outputs(missing, after)
    assert comparison["status"] == "partial"
    assert comparison["counts"]["delta"] is None
    assert not comparison["schema"]["comparable"]
    assert comparison["keyed_diff"]["added_count"] is None
    assert comparison["keyed_diff"]["reason"] == "before_snapshot_unavailable"


def test_nonfinite_dates_decimals_and_nulls_are_legal_json(tmp_path):
    path = _database(tmp_path, """create table result(id int,value double,day date,precise decimal(18,4));
insert into result values(1,'NaN','2026-10-25',1.2345),(2,'Infinity',null,2.0000),(3,'-Infinity','2026-01-01',null),(4,null,null,0)""")
    snapshot = capture_output(path, "result", ["id"])
    assert snapshot["available"], snapshot
    assert snapshot["column_stats"]["value"] == {"null_count": 1, "nonfinite_count": 3}
    assert [row["value"] for row in snapshot["rows"]] == ["NaN", "Infinity", "-Infinity", None]
    assert snapshot["rows"][0]["day"] == "2026-10-25"
    assert snapshot["rows"][0]["precise"] == "1.2345"
    json.dumps(snapshot, allow_nan=False)
    json.dumps(compare_outputs(snapshot, snapshot), allow_nan=False)


def test_truncated_rows_never_become_full_keyed_statistics(tmp_path):
    path = _database(tmp_path, "create table result as select range as id from range(5007)")
    snapshot = capture_output(path, "result", ["id"])
    assert snapshot["key_valid"]
    assert snapshot["row_count"] == 5007
    assert len(snapshot["rows"]) == 5000 and len(snapshot["sample_rows"]) == 10
    assert snapshot["truncated"]
    comparison = compare_outputs(snapshot, snapshot)
    assert comparison["status"] == "partial"
    assert not comparison["keyed_diff"]["supported"]
    assert comparison["keyed_diff"]["changed_count"] is None
