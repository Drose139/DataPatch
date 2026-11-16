"""Read-only data snapshots and evidence of changes, independent of any oracle.

Differences describe impact, not correctness. The caller must separately record
whether the final SQL built successfully before treating an after-image as fresh.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
from typing import Any

import duckdb

MAX_SNAPSHOT_ROWS = 5000
MAX_SAMPLE_ROWS = 10
MAX_DIFF_SAMPLES = 5


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_name(table: str) -> str:
    # Public task grains use ordinary qualified names. Quote every component so
    # the table argument cannot introduce another SQL expression or statement.
    parts = table.split(".")
    if not parts or any(not part.strip() for part in parts):
        raise ValueError("Expected a table name or schema.table")
    return ".".join(_quoted(part.strip().removeprefix('"').removesuffix('"').replace('""', '"')) for part in parts)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)  # Preserve exact decimal precision.
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def capture_output(database_path: Path, table: str, key_columns: list[str] | None = None) -> dict:
    """Capture actual output metadata and at most 5000 rows without writing.

    A key is never inferred. Validity is checked against the entire table, even
    when the captured row set is truncated. Snapshots contain no expected data.
    """
    keys = list(key_columns or [])
    snapshot: dict[str, Any] = {
        "table": table, "available": False, "error": None, "schema": [],
        "row_count": None, "key_columns": keys, "key_valid": False,
        "key_validation": {"status": "unavailable", "null_key_rows": None,
                           "duplicate_key_groups": None, "duplicate_key_rows": None},
        "rows": [], "sample_rows": [], "truncated": False,
        "column_stats": {}, "column_stats_truncated": False,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "row_limit": MAX_SNAPSHOT_ROWS,
    }
    try:
        relation = _table_name(table)
        with duckdb.connect(str(database_path), read_only=True) as connection:
            description = connection.execute(f"select * from {relation} limit 0").description
            schema = [{"name": item[0], "type": str(item[1])} for item in description]
            columns = [item["name"] for item in schema]
            snapshot["schema"] = schema
            snapshot["row_count"] = connection.execute(f"select count(*) from {relation}").fetchone()[0]
            snapshot["truncated"] = snapshot["row_count"] > MAX_SNAPSHOT_ROWS
            status = snapshot["key_validation"]
            if not keys:
                status["status"] = "not_declared"
            elif len(keys) != len(set(keys)):
                status["status"] = "duplicate_key_columns"
            elif any(key not in columns for key in keys):
                status["status"] = "missing_columns"
                status["missing_columns"] = [key for key in keys if key not in columns]
            else:
                key_sql = ", ".join(_quoted(key) for key in keys)
                null_predicate = " or ".join(f"{_quoted(key)} is null" for key in keys)
                null_rows = connection.execute(f"select count(*) from {relation} where {null_predicate}").fetchone()[0]
                duplicate_groups, duplicate_rows = connection.execute(f"select count(*), coalesce(sum(n),0) from (select count(*) as n from {relation} group by {key_sql} having count(*)>1)").fetchone()
                status.update({"null_key_rows": null_rows, "duplicate_key_groups": duplicate_groups, "duplicate_key_rows": int(duplicate_rows)})
                status["status"] = "null_keys" if null_rows else "duplicate_keys" if duplicate_groups else "valid"
                snapshot["key_valid"] = not null_rows and not duplicate_groups
            expressions = []
            for index, column in enumerate(schema[:60]):
                quoted = _quoted(column["name"])
                expressions.append(f"count(*) filter(where {quoted} is null) as n{index}")
                is_float = column["type"].upper() in {"FLOAT", "DOUBLE", "REAL"}
                expressions.append(f"count(*) filter(where {quoted} is not null and not isfinite({quoted})) as f{index}" if is_float else f"0 as f{index}")
            if expressions:
                stats = connection.execute(f"select {', '.join(expressions)} from {relation}").fetchone()
                snapshot["column_stats"] = {column["name"]: {"null_count": stats[index * 2], "nonfinite_count": stats[index * 2 + 1]} for index, column in enumerate(schema[:60])}
            snapshot["column_stats_truncated"] = len(schema) > 60
            rows = connection.execute(f"select * from {relation} limit {MAX_SNAPSHOT_ROWS}").fetchall()
            snapshot["rows"] = [{name: _json_value(value) for name, value in zip(columns, row)} for row in rows]
            snapshot["sample_rows"] = snapshot["rows"][:MAX_SAMPLE_ROWS]
        snapshot["available"] = True
    except Exception as exc:
        snapshot["error"] = str(exc)[:1500]
        snapshot["key_validation"]["status"] = "unavailable"
    return snapshot


def compare_outputs(before: dict, after: dict) -> dict:
    """Compare complete keyed snapshots and schema/count impact where available."""
    result: dict[str, Any] = {
        "status": "unavailable", "schema": {"added": [], "removed": [], "type_changed": [], "comparable": False},
        "counts": {"before": before.get("row_count") if before.get("available") else None,
                   "after": after.get("row_count") if after.get("available") else None, "delta": None},
        "keyed_diff": {"supported": False, "reason": "snapshots_unavailable", "keys": [],
                       "added_count": None, "removed_count": None, "changed_count": None,
                       "unchanged_count": None, "samples": {"added": [], "removed": [], "changed": []}},
        "notes": ["Data differences describe impact and do not prove business correctness. Build freshness must be checked separately."],
    }
    left_available, right_available = bool(before.get("available")), bool(after.get("available"))
    if not left_available or not right_available:
        result["status"] = "partial" if left_available or right_available else "unavailable"
        missing = "before" if not left_available else "after"
        result["keyed_diff"]["reason"] = f"{missing}_snapshot_unavailable"
        result["notes"].append("A missing or failed baseline cannot establish that there was no change.")
        return result
    result["status"] = "partial" if before.get("truncated") or after.get("truncated") else "complete"
    left_schema = {column["name"]: column["type"] for column in before.get("schema", [])}
    right_schema = {column["name"]: column["type"] for column in after.get("schema", [])}
    result["schema"] = {
        "added": [{"name": name, "type": right_schema[name]} for name in right_schema.keys() - left_schema.keys()],
        "removed": [{"name": name, "type": left_schema[name]} for name in left_schema.keys() - right_schema.keys()],
        "type_changed": [{"name": name, "before": left_schema[name], "after": right_schema[name]} for name in left_schema.keys() & right_schema.keys() if left_schema[name] != right_schema[name]],
        "comparable": True,
    }
    for field in ("added", "removed", "type_changed"):
        result["schema"][field].sort(key=lambda column: column["name"])
    if isinstance(result["counts"]["before"], int) and isinstance(result["counts"]["after"], int):
        result["counts"]["delta"] = result["counts"]["after"] - result["counts"]["before"]
    diff = result["keyed_diff"]
    keys = before.get("key_columns") or []
    diff["keys"] = keys
    if not keys or not after.get("key_columns"):
        diff["reason"] = "key_not_declared"
        return result
    if keys != after.get("key_columns"):
        diff["reason"] = "key_columns_differ"
        return result
    if not before.get("key_valid") or not after.get("key_valid"):
        diff["reason"] = "invalid_key: before=" + before.get("key_validation", {}).get("status", "unknown") + ", after=" + after.get("key_validation", {}).get("status", "unknown")
        return result
    if any(left_schema.get(key) != right_schema.get(key) for key in keys):
        diff["reason"] = "key_column_types_changed"
        return result
    if before.get("truncated") or after.get("truncated"):
        diff["reason"] = "snapshot_rows_truncated; full keyed counts unavailable"
        result["notes"].append("Schema and row counts cover the table; keyed rows exceed the snapshot limit. Samples are not full-table statistics.")
        return result
    comparable = [name for name in left_schema if name not in keys and right_schema.get(name) == left_schema[name]]
    def token(row: dict) -> str:
        return json.dumps([row.get(key) for key in keys], sort_keys=True, ensure_ascii=False, allow_nan=False)
    left = {token(row): row for row in before.get("rows", [])}
    right = {token(row): row for row in after.get("rows", [])}
    # Snapshot metadata must agree with the captured rows before claiming totals.
    if len(left) != before["row_count"] or len(right) != after["row_count"]:
        diff["reason"] = "snapshot_rows_incomplete_or_duplicate"
        result["status"] = "partial"
        return result
    added, removed = sorted(right.keys() - left.keys()), sorted(left.keys() - right.keys())
    changed, unchanged = [], 0
    for key in sorted(left.keys() & right.keys()):
        columns = [name for name in comparable if left[key].get(name) != right[key].get(name)]
        if columns:
            changed.append({"key": {name: right[key][name] for name in keys}, "before": left[key], "after": right[key], "changed_columns": columns})
        else:
            unchanged += 1
    diff.update({"supported": True, "reason": "complete snapshots with a declared unique non-null key",
                 "added_count": len(added), "removed_count": len(removed), "changed_count": len(changed),
                 "unchanged_count": unchanged, "compared_columns": comparable,
                 "samples": {"added": [right[key] for key in added[:MAX_DIFF_SAMPLES]], "removed": [left[key] for key in removed[:MAX_DIFF_SAMPLES]], "changed": changed[:MAX_DIFF_SAMPLES]}})
    result["notes"].append("Changed rows compare only common columns with identical types; added/removed/type-changed columns are reported in schema separately. Values are not rounded.")
    return result
