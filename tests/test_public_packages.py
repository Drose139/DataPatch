"""Pinned local package provenance, byte integrity, and real offline dbt deps."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_package_cache", ROOT / "integrations/public_packages.py")
packages = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(packages)


@pytest.fixture
def cached_package(tmp_path):
    source = tmp_path / "successful-project"
    library = source / "dbt_packages/dbt_utils"
    (library / "macros").mkdir(parents=True)
    (library / "dbt_project.yml").write_bytes(b"name: dbt_utils\nversion: '0.1.0'\nconfig-version: 2\n")
    (library / "macros/example.sql").write_bytes(b"{% macro example() %}1{% endmacro %}\n")
    (source / "packages.yml").write_bytes(b"packages:\r\n  - package: dbt-labs/dbt_utils\r\n    version: '1.3.3'\r\n")
    (source / "package-lock.yml").write_bytes(b"packages:\n  - name: dbt_utils\n    package: dbt-labs/dbt_utils\n    version: 1.3.3\n")
    log = tmp_path / "deps.json"
    log.write_text(json.dumps({"command": ["dbt", "deps"], "returncode": 0,
                               "stdout": "Installing dbt-labs/dbt_utils\nInstalled from version 1.3.3\n"}), encoding="utf-8")
    cache = tmp_path / "verified-cache"
    packages.create_cache(source, log, cache)
    case, project = tmp_path / "case", tmp_path / "case/project"
    project.mkdir(parents=True)
    for name in ("packages.yml", "package-lock.yml"):
        shutil.copyfile(source / name, project / name)
    (project / "dbt_project.yml").write_text("name: offline_project\nversion: '1.0.0'\nconfig-version: 2\nprofile: offline_project\n", encoding="utf-8")
    return source, cache, case, project


def test_local_install_preserves_source_bytes_and_receipt(cached_package):
    source, cache, case, project = cached_package
    originals = {name: (project / name).read_bytes() for name in ("packages.yml", "package-lock.yml")}
    result = packages.install_cache(cache, case, project)
    assert result["resolved_version"] == "1.3.3"
    assert packages.validate_cache(cache)["package_project_declared_version"] == "0.1.0"
    assert (case / "preparation/packages.original.yml").read_bytes() == originals["packages.yml"]
    assert (case / "preparation/package-lock.original.yml").read_bytes() == originals["package-lock.yml"]
    assert all((source / name).read_bytes() == data for name, data in originals.items())
    assert yaml.safe_load((project / "packages.yml").read_bytes()) == {"packages": [{"local": "../dbt_packages/dbt_utils"}]}
    assert not (project / "package-lock.yml").exists()
    assert (case / "preparation/packages-cache-receipt.json").read_bytes() == (cache / "receipt.json").read_bytes()
    assert packages._files(Path(result["installed_directory"])) == result["files"]
    from datapatch.workspace import Workspace
    assert not any("dbt_packages" in Path(name).parts for name in Workspace(case, project_dir=project).list_files()["files"])


def test_corrupt_cached_file_is_rejected_before_rewriting_project(cached_package):
    _, cache, case, project = cached_package
    original = (project / "packages.yml").read_bytes()
    (cache / "dbt_utils/macros/example.sql").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA manifest mismatch"):
        packages.install_cache(cache, case, project)
    assert (project / "packages.yml").read_bytes() == original
    assert not (case / "dbt_packages").exists()


def test_native_prepare_records_verified_cache_without_changing_snapshot(cached_package, tmp_path):
    source, cache, _, _ = cached_package
    adapter_spec = importlib.util.spec_from_file_location("cached_native_adapter", ROOT / "integrations/harbor_agent.py")
    adapter = importlib.util.module_from_spec(adapter_spec)
    adapter_spec.loader.exec_module(adapter)
    snapshot = tmp_path / "snapshot"
    project = snapshot / "base-image/dbt_models_duckdb"
    project.mkdir(parents=True)
    for name in ("packages.yml", "package-lock.yml"):
        shutil.copyfile(source / name, project / name)
    database = snapshot / "base-image/database/retail.duckdb"
    database.parent.mkdir()
    database.write_bytes(b"fixed-input")
    task = "cohort-retention-matrix"
    instruction = snapshot / "tasks" / task / "instruction.md"
    instruction.parent.mkdir(parents=True)
    instruction.write_text("Create cohort_retention_matrix", encoding="utf-8")
    (snapshot / "snapshot-lock.json").write_text(json.dumps({"commit": adapter.PINNED_COMMIT,
        "tasks": [task], "database": {"bytes": len(b"fixed-input")}}), encoding="utf-8")
    case = tmp_path / "prepared-case"
    meta = adapter.prepare_native_case(snapshot, case, task, initialize=False, packages_cache=cache)
    adaptation = meta["runtime_adaptations"]["packages_cache"]
    assert adaptation["receipt_sha256"] == hashlib.sha256((cache / "receipt.json").read_bytes()).hexdigest()
    assert adaptation["files"] == packages.validate_cache(cache)["files"]
    assert (project / "packages.yml").read_bytes() == (source / "packages.yml").read_bytes()
    assert (project / "package-lock.yml").read_bytes() == (source / "package-lock.yml").read_bytes()
    assert yaml.safe_load((case / "project/packages.yml").read_bytes())["packages"] == [{"local": "../dbt_packages/dbt_utils"}]


@pytest.mark.parametrize("wrong_version_location", ["receipt", "requirement"])
def test_mismatched_package_version_is_rejected(cached_package, wrong_version_location):
    _, cache, case, project = cached_package
    if wrong_version_location == "receipt":
        path = cache / "receipt.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["resolved_version"] = "1.3.2"
        path.write_text(json.dumps(receipt), encoding="utf-8")
    else:
        (project / "packages.yml").write_text("packages:\n - package: dbt-labs/dbt_utils\n   version: '1.3.2'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="1.3.3"):
        packages.install_cache(cache, case, project)


def test_real_dbt_deps_resolves_local_library_with_network_connections_blocked(cached_package):
    _, cache, case, project = cached_package
    packages.install_cache(cache, case, project)
    code = """
import socket, sys
def forbidden_network(*args, **kwargs):
    raise AssertionError('Offline dependency resolution attempted a network connection')
socket.socket.connect = forbidden_network
socket.create_connection = forbidden_network
from dbt.cli.main import dbtRunner
result = dbtRunner().invoke(['deps', '--project-dir', sys.argv[1]])
if not result.success:
    print(repr(result.exception))
raise SystemExit(0 if result.success else 1)
"""
    environment = {**os.environ, "DBT_SEND_ANONYMOUS_USAGE_STATS": "false", "PYTHONUTF8": "1"}
    result = subprocess.run([sys.executable, "-c", code, str(project)], cwd=project, env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Installed from <local" in result.stdout
    assert packages._files(project / "dbt_packages/dbt_utils") == packages.validate_cache(cache)["files"]
