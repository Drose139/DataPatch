"""Fetch a pinned, allowlisted data-eng-bench snapshot without exposing answers.

No solution files or task verifiers are extracted. The compressed upstream
archive is streamed and discarded; only image inputs and selected instructions
are retained. Large LFS data is separately checked against its SHA-256 pointer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

REPOSITORY = "Snowflake-Labs/data-eng-bench"
PINNED_COMMIT = "a3278ad102829a6084dde086244a0ef665a8011c"
DEFAULT_TASKS = ("dbt-fix-refund-reconciliation", "dbt-fix-division-by-zero")
SUPPORTED_TASKS = DEFAULT_TASKS + (
    "dbt-fix-inventory-model", "dbt-fix-product-metrics", "dbt-fix-timezone-sales",
    "dbt-fix-daily-revenue", "dbt-exchange-rate-settlement-date", "cohort-retention-matrix",
    "dbt-carrier-delivery-performance",
)
# Task-specific inputs only. In particular, never retain arbitrary files from
# an environment directory: newer tasks also place their overlay at its root.
BUG_MODEL_INPUTS = {
    "dbt-fix-refund-reconciliation": "environment/data/rpt_return_reconciliation.sql",
    "dbt-fix-division-by-zero": "environment/data/rpt_customer_metrics.sql",
    "dbt-fix-inventory-model": "environment/data/rpt_product_inventory_metrics.sql",
    "dbt-fix-product-metrics": None,
    "dbt-fix-timezone-sales": "environment/int_sales__orders_enriched.sql",
    "dbt-fix-daily-revenue": "environment/rpt_order_daily_summary.sql",
    "dbt-exchange-rate-settlement-date": None,
    "cohort-retention-matrix": None,
    "dbt-carrier-delivery-performance": "environment/rpt_carrier_performance.sql",
}
MODEL_PREFIX = "base-image/dbt_models_duckdb/"
DATABASE_PATH = "base-image/database/retail.duckdb"
ROOT_FILES = {"LICENSE", "NOTICE", "README.md", "base-image/Dockerfile", "base-image/fix_data.py", DATABASE_PATH}


def selected_path(path: str, tasks: tuple[str, ...]) -> bool:
    """Keep runtime inputs, not reference patches or hidden task assertions."""
    parts = PurePosixPath(path).parts
    if not parts or ".." in parts or path.startswith("/"):
        return False
    if path in ROOT_FILES or path.startswith(MODEL_PREFIX):
        return True
    return any(
        path in {f"tasks/{task}/instruction.md", f"tasks/{task}/task.toml", f"tasks/{task}/environment/Dockerfile"}
        or (BUG_MODEL_INPUTS.get(task) is not None and path == f"tasks/{task}/{BUG_MODEL_INPUTS[task]}")
        for task in tasks
    )


def request(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "DataPatch-benchmark-fetch/0.1"}), timeout=120)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_snapshot(destination: Path, tasks: tuple[str, ...], *, include_database: bool = True) -> dict:
    if not tasks or len(tasks) != len(set(tasks)) or any(task not in SUPPORTED_TASKS for task in tasks):
        raise ValueError("Choose a nonempty, unique subset of the supported public tasks")
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    lock_path = destination / "snapshot-lock.json"
    if lock_path.exists():
        previous = json.loads(lock_path.read_text(encoding="utf-8"))
        if previous.get("commit") != PINNED_COMMIT:
            raise ValueError("Destination belongs to a different benchmark revision; use a new directory")
    archive_url = f"https://codeload.github.com/{REPOSITORY}/tar.gz/{PINNED_COMMIT}"
    records: list[dict] = []
    pointer = None
    with request(archive_url) as response, tarfile.open(fileobj=response, mode="r|gz") as archive:
        for member in archive:
            relative = member.name.partition("/")[2]
            if not member.isfile() or not selected_path(relative, tasks):
                continue
            source = archive.extractfile(member)
            if source is None:
                continue
            data = source.read()
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative == DATABASE_PATH:
                pointer_text = data.decode("ascii")
                oid = re.search(r"^oid sha256:([a-f0-9]{64})$", pointer_text, re.M)
                size = re.search(r"^size ([0-9]+)$", pointer_text, re.M)
                if not oid or not size:
                    raise ValueError("Expected a Git LFS pointer for retail.duckdb")
                pointer = {"sha256": oid.group(1), "bytes": int(size.group(1))}
                # Preserve provenance without putting a text pointer in place of a DB.
                target.with_suffix(".duckdb.lfs-pointer").write_bytes(data)
                continue
            target.write_bytes(data)
            records.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    if pointer is None:
        raise ValueError("Pinned archive did not contain the database LFS pointer")
    for task in tasks:
        if not (destination / "tasks" / task / "instruction.md").is_file():
            raise ValueError(f"Unknown task at pinned revision: {task}")
    database = destination / DATABASE_PATH
    if include_database:
        valid_cached = database.is_file() and database.stat().st_size == pointer["bytes"] and sha256_file(database) == pointer["sha256"]
        if not valid_cached:
            media_url = f"https://media.githubusercontent.com/media/{REPOSITORY}/{PINNED_COMMIT}/{DATABASE_PATH}"
            partial = database.with_suffix(".duckdb.partial")
            print(f"Downloading database ({pointer['bytes']:,} bytes)", flush=True)
            with request(media_url) as response, partial.open("wb") as output:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    output.write(chunk)
            if partial.stat().st_size != pointer["bytes"] or sha256_file(partial) != pointer["sha256"]:
                raise ValueError("Downloaded DuckDB file does not match the pinned LFS hash")
            partial.replace(database)
        records.append({"path": DATABASE_PATH, **pointer})
    lock = {"repository": REPOSITORY, "commit": PINNED_COMMIT, "tasks": list(tasks), "database": pointer, "database_downloaded": include_database,
            "files": sorted(records, key=lambda x: x["path"]), "reference_solutions_retained": False,
            "task_verifiers_retained": False, "archive_selection": "full compressed stream in transport; non-allowlisted members discarded without extraction or retention"}
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return lock


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path("external/data-eng-bench"))
    parser.add_argument("--task", action="append", choices=SUPPORTED_TASKS, help="Repeat for a fixed public subset; default remains the historical two tasks")
    parser.add_argument("--metadata-only", action="store_true", help="Skip the 489MB database; keep its expected hash")
    args = parser.parse_args()
    lock = fetch_snapshot(args.destination, tuple(args.task or DEFAULT_TASKS), include_database=not args.metadata_only)
    print(json.dumps({"destination": str(args.destination.resolve()), "commit": lock["commit"], "tasks": lock["tasks"], "files": len(lock["files"]), "database_downloaded": lock["database_downloaded"]}, indent=2))


if __name__ == "__main__":
    main()
