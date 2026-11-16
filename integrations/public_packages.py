"""Verified local copy of the benchmark's already-resolved dbt_utils package.

The package version comes from the successful deps log and package lock, not
dbt_utils/dbt_project.yml (whose internal project version is independently 0.1.0).
No registry request or network retry is performed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

import yaml

PACKAGE = "dbt-labs/dbt_utils"
VERSION = "1.3.3"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(directory: Path) -> dict[str, str]:
    return {p.relative_to(directory).as_posix(): _sha(p)
            for p in sorted(directory.rglob("*")) if p.is_file()}


def _requirement(path: Path) -> None:
    packages = (yaml.safe_load(path.read_bytes()) or {}).get("packages")
    if packages != [{"package": PACKAGE, "version": VERSION}]:
        raise ValueError("Original packages.yml must pin only dbt-labs/dbt_utils 1.3.3")


def _evidence(packages: Path, lock: Path, deps_log: Path) -> None:
    _requirement(packages)
    resolved = (yaml.safe_load(lock.read_bytes()) or {}).get("packages", [])
    if len(resolved) != 1 or resolved[0].get("package") != PACKAGE or str(resolved[0].get("version")) != VERSION:
        raise ValueError("Successful source lock must resolve dbt_utils 1.3.3")
    log = json.loads(deps_log.read_text(encoding="utf-8"))
    if log.get("returncode") != 0 or "deps" not in log.get("command", []) or "Installed from version 1.3.3" not in log.get("stdout", ""):
        raise ValueError("Cache requires an archived successful dbt deps 1.3.3 log")


def create_cache(source_project: Path, deps_log: Path, output: Path) -> dict:
    source_project, deps_log, output = source_project.resolve(), deps_log.resolve(), output.resolve()
    if output.exists():
        raise ValueError("Package cache output must be new")
    packages, lock = source_project / "packages.yml", source_project / "package-lock.yml"
    _evidence(packages, lock, deps_log)
    source = source_project / "dbt_packages/dbt_utils"
    project = yaml.safe_load((source / "dbt_project.yml").read_bytes())
    if project.get("name") != "dbt_utils":
        raise ValueError("Cached package project must be named dbt_utils")
    files = _files(source)
    output.mkdir(parents=True)
    shutil.copytree(source, output / "dbt_utils")
    evidence = {}
    (output / "evidence").mkdir()
    for name, path in (("packages", packages), ("lock", lock), ("deps_log", deps_log)):
        destination = output / "evidence" / (name + path.suffix)
        destination.write_bytes(path.read_bytes())
        evidence[name] = {"path": destination.relative_to(output).as_posix(), "sha256": _sha(destination),
                          "source_path": str(path)}
    if _files(output / "dbt_utils") != files:
        raise ValueError("Copied package bytes differ from successful source")
    receipt = {"schema_version": 1, "package": PACKAGE, "resolved_version": VERSION,
               "origin": "previous successful pinned dbt deps; no new registry resolution",
               "source_project": str(source_project), "package_project_declared_version": str(project.get("version")),
               "files": files, "evidence": evidence}
    (output / "receipt.json").write_bytes((json.dumps(receipt, indent=2) + "\n").encode("utf-8"))
    return receipt


def validate_cache(cache: Path) -> dict:
    cache = cache.resolve()
    receipt = json.loads((cache / "receipt.json").read_text(encoding="utf-8"))
    if receipt.get("schema_version") != 1 or receipt.get("package") != PACKAGE or receipt.get("resolved_version") != VERSION:
        raise ValueError("Cache receipt package/version must be dbt_utils 1.3.3")
    actual = _files(cache / "dbt_utils")
    if not actual or actual != receipt.get("files"):
        raise ValueError("Package cache file SHA manifest mismatch")
    for item in receipt["evidence"].values():
        path = (cache / item["path"]).resolve()
        if not path.is_relative_to(cache) or _sha(path) != item["sha256"]:
            raise ValueError("Package cache source evidence SHA mismatch")
    _evidence(*(cache / receipt["evidence"][name]["path"] for name in ("packages", "lock", "deps_log")))
    if yaml.safe_load((cache / "dbt_utils/dbt_project.yml").read_bytes()).get("name") != "dbt_utils":
        raise ValueError("Cached package project must be named dbt_utils")
    return receipt


def install_cache(cache: Path, case: Path, project: Path) -> dict:
    cache, case, project = cache.resolve(), case.resolve(), project.resolve()
    receipt = validate_cache(cache)
    if not project.is_relative_to(case):
        raise ValueError("Runtime project must be inside the prepared case")
    packages, lock = project / "packages.yml", project / "package-lock.yml"
    _requirement(packages)
    preparation = case / "preparation"
    preparation.mkdir(exist_ok=True)
    originals = {"source_packages_sha256": _sha(packages), "source_lock_sha256": _sha(lock) if lock.exists() else None}
    (preparation / "packages.original.yml").write_bytes(packages.read_bytes())
    if lock.exists():
        (preparation / "package-lock.original.yml").write_bytes(lock.read_bytes())
        lock.unlink()  # Runtime copy only; dbt creates its new local-package lock.
    # Workspace already excludes every dbt_packages directory from discovery.
    # Keep the source copy separate from project/dbt_packages installed by dbt.
    destination = case / "dbt_packages/dbt_utils"
    destination.parent.mkdir(exist_ok=True)
    shutil.copytree(cache / "dbt_utils", destination)
    if _files(destination) != receipt["files"]:
        raise ValueError("Installed package bytes differ from the verified receipt")
    packages.write_bytes(b"packages:\n  - local: ../dbt_packages/dbt_utils\n")
    archived_receipt = preparation / "packages-cache-receipt.json"
    archived_receipt.write_bytes((cache / "receipt.json").read_bytes())
    return {"cache_path": str(cache), "package": PACKAGE, "resolved_version": VERSION,
            "receipt_path": str(cache / "receipt.json"), "receipt_sha256": _sha(cache / "receipt.json"),
            "archived_receipt": str(archived_receipt), **originals,
            "original_packages_path": str(preparation / "packages.original.yml"),
            "original_lock_path": str(preparation / "package-lock.original.yml") if originals["source_lock_sha256"] else None,
            "local_packages_sha256": _sha(packages), "installed_directory": str(destination), "files": receipt["files"],
            "adaptation": "Runtime local path to byte-identical pinned package; model SQL, source data, and verifier assertions unchanged"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--deps-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = create_cache(args.source_project, args.deps_log, args.output)
    print(json.dumps({"cache": str(args.output.resolve()), "package": PACKAGE, "resolved_version": VERSION,
                      "files": len(receipt["files"]), "receipt_sha256": _sha(args.output / "receipt.json")}))
