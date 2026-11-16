"""Native adapter for fixed pinned public data-eng-bench development subsets.

This reproduces selected task inputs on a local dbt runtime. It does NOT claim
to be a Docker sandbox or an official Harbor leaderboard run. Evaluation stays
outside the agent's project and downloads no reference solution.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PUBLIC_TASK_MODELS = {
    "dbt-fix-refund-reconciliation": "models/marts/sales/rpt_return_reconciliation.sql",
    "dbt-fix-division-by-zero": "models/marts/customer/rpt_customer_metrics.sql",
    "dbt-fix-inventory-model": "models/marts/inventory/rpt_product_inventory_metrics.sql",
    "dbt-fix-product-metrics": "models/marts/product/fct_product_metrics.sql",
    "dbt-fix-timezone-sales": "models/intermediate/sales/int_sales__orders_enriched.sql",
    "dbt-fix-daily-revenue": "models/marts/sales/rpt_order_daily_summary.sql",
    "dbt-exchange-rate-settlement-date": "models/marts/finance/fact_revenue.sql",
    "cohort-retention-matrix": "models/marts/marketing/cohort_retention_matrix.sql",
    "dbt-carrier-delivery-performance": "models/marts/sales/rpt_carrier_performance.sql",
}
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
LEGACY_TASKS = ("dbt-fix-refund-reconciliation", "dbt-fix-division-by-zero")
CREATE_MODEL_ANCESTORS = {
    "dbt-fix-product-metrics": ("stg_orders__order_lines", "stg_orders__orders", "stg_product__product_variants", "stg_product__products"),
    "cohort-retention-matrix": ("stg_customer__customers", "stg_orders__orders"),
}
PYTEST_EXIT_STATUS_TASKS = {"dbt-fix-product-metrics", "dbt-fix-timezone-sales", "dbt-fix-daily-revenue",
                            "dbt-exchange-rate-settlement-date", "cohort-retention-matrix"}
EXPLICIT_GRADING_TASKS = {"dbt-carrier-delivery-performance"}
PINNED_COMMIT = "a3278ad102829a6084dde086244a0ef665a8011c"
REPOSITORY = "Snowflake-Labs/data-eng-bench"


def pytest_counts(stdout: str) -> dict[str, int]:
    """Match the pinned shell harness's final pytest count extraction."""
    result = {}
    for key, label in (("passed", "passed"), ("failed", "failed"), ("errors", "errors?"), ("skipped", "skipped")):
        matches = re.findall(r"\b(\d+) (?=" + label + r"\b)", stdout)
        result[key] = int(matches[-1]) if matches else 0
    return result


def pytest_exit_reward(returncode: int, counts: dict[str, int]) -> float:
    return float(returncode == 0 and counts["passed"] > 0 and not any(counts[key] for key in ("failed", "errors", "skipped")))


def verify_target_build(build: dict, project: Path, model_path: str) -> dict:
    """A zero-exit dbt no-op is not evidence the requested model built."""
    name = Path(model_path).stem
    target_ids = set()
    manifest_path = project / "target/manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        target_ids = {key for key, node in manifest.get("nodes", {}).items()
                      if node.get("resource_type") == "model" and node.get("name") == name
                      and node.get("original_file_path", model_path).replace("\\", "/") == model_path}
    nodes = build.get("nodes") or []
    results_path = project / "target/run_results.json"
    if results_path.is_file():
        results = json.loads(results_path.read_text(encoding="utf-8"))
        nodes = [{"id": row.get("unique_id"), "status": row.get("status")} for row in results.get("results", [])]
    matched = [row for row in nodes if (row.get("id") in target_ids if manifest_path.is_file()
               else str(row.get("id", "")).startswith("model.") and str(row["id"]).rsplit(".", 1)[-1] == name)]
    target_success = any(row.get("status") == "success" for row in matched)
    checked = {**build, "process_success": build.get("success") is True, "target_model": name,
               "target_model_ids": sorted(target_ids), "target_model_success": target_success,
               "success": build.get("success") is True and target_success}
    if not target_success:
        checked["target_verification_error"] = "No successful result for the requested target model; a missing/skipped target or zero-node dbt run is not a successful build"
    return checked


def runtime_versions() -> dict[str, str]:
    versions = {"python": sys.version.split()[0], "platform": sys.platform}
    for package in ("duckdb", "dbt-core", "dbt-duckdb"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not installed"
    return versions


def dbt_executable() -> str:
    executable = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    if executable.is_file():
        return str(executable)
    found = shutil.which("dbt")
    if not found:
        raise RuntimeError("dbt executable missing; install dbt-duckdb in the active Python environment")
    return found


def native_environment(case_dir: Path) -> dict[str, str]:
    case_dir = case_dir.resolve()
    env = os.environ.copy()
    env.update({"DB_TYPE": "duckdb", "DUCKDB_PATH": str(case_dir / "database" / "retail.duckdb"),
                "DBT_PROJECT_DIR_DUCKDB": str(case_dir / "project"), "DBT_PROFILES_DIR": str(case_dir / "project"),
                "DBT_SEND_ANONYMOUS_USAGE_STATS": "false", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def run_recorded(command: list[str], *, cwd: Path, env: dict[str, str], log: Path, timeout: int = 1200) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({"command": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}, indent=2), encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Preparation command failed ({result.returncode}); see {log}")


def prepare_native_case(snapshot: Path, case_dir: Path, task_id: str, *, initialize: bool = True, full_base_build: bool = False, duckdb_timezone: str | None = None, packages_cache: Path | None = None) -> dict:
    """Copy clean inputs and reproduce the original fix-or-create task setup."""
    if duckdb_timezone not in (None, "UTC"):
        raise ValueError("Explicit DuckDB timezone must be UTC or omitted")
    if task_id not in PUBLIC_TASK_MODELS:
        raise ValueError(f"Supported fixed subset: {', '.join(PUBLIC_TASK_MODELS)}")
    snapshot, case_dir = snapshot.resolve(), case_dir.resolve()
    lock = json.loads((snapshot / "snapshot-lock.json").read_text(encoding="utf-8"))
    if lock["commit"] != PINNED_COMMIT or task_id not in lock["tasks"]:
        raise ValueError("Snapshot revision/subset does not match this adapter")
    source_database = snapshot / "base-image/database/retail.duckdb"
    if not source_database.is_file() or source_database.stat().st_size != lock["database"]["bytes"]:
        raise ValueError("Full DuckDB database missing; run fetch without --metadata-only")
    # Never reuse a case that may already contain a model's previous patch.
    if case_dir.exists() and any(case_dir.iterdir()):
        raise ValueError("Case directory must be empty; choose a fresh path for every independent attempt")
    case_dir.mkdir(parents=True, exist_ok=True)
    project = case_dir / "project"
    shutil.copytree(snapshot / "base-image/dbt_models_duckdb", project)
    database_dir = case_dir / "database"
    database_dir.mkdir()
    shutil.copy2(source_database, database_dir / "retail.duckdb")
    env = native_environment(case_dir)
    # Absolute path avoids changing dbt's database when the caller's cwd changes.
    # POSIX slashes are accepted by DuckDB on Windows and avoid YAML escaping.
    profile = "retail_dw_master:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n      path: '" + (database_dir / "retail.duckdb").as_posix().replace("'", "''") + "'\n      schema: main\n      threads: 4\n"
    if duckdb_timezone is not None:
        profile += "      settings:\n        TimeZone: 'UTC'\n"
    (project / "profiles.yml").write_text(profile, encoding="utf-8")
    package_adaptation = None
    if packages_cache is not None:
        spec = importlib.util.spec_from_file_location("public_packages", Path(__file__).with_name("public_packages.py"))
        helper = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(helper)
        package_adaptation = helper.install_cache(packages_cache, case_dir, project)
    logs = case_dir / "preparation"
    model_name = Path(PUBLIC_TASK_MODELS[task_id]).stem
    create_model = task_id in CREATE_MODEL_ANCESTORS
    selectors = CREATE_MODEL_ANCESTORS.get(task_id, (model_name,))
    if create_model and (project / PUBLIC_TASK_MODELS[task_id]).exists():
        raise ValueError("Create-model task unexpectedly contains a target SQL file in the pinned base")
    if initialize:
        run_recorded([sys.executable, str(snapshot / "base-image/fix_data.py")], cwd=project, env=env, log=logs / "fix_data.json")
        run_recorded([dbt_executable(), "deps", "--profiles-dir", str(project)], cwd=project, env=env, log=logs / "deps.json")
        command = [dbt_executable(), "run", "--profiles-dir", str(project), "--target", "dev"]
        if not full_base_build:
            command += ["--select", *("+" + name for name in selectors)]
        run_recorded(command, cwd=project, env=env, log=logs / "base_build.json")
    overlay = BUG_MODEL_INPUTS[task_id]
    if overlay is not None:
        buggy = snapshot / "tasks" / task_id / overlay
        shutil.copy2(buggy, project / PUBLIC_TASK_MODELS[task_id])
    instruction = (snapshot / "tasks" / task_id / "instruction.md").read_text(encoding="utf-8")
    instruction = instruction.replace("/app/dbt_models_duckdb", project.as_posix()).replace("/app/database/retail.duckdb", (database_dir / "retail.duckdb").as_posix())
    # The Snowflake path stays in the original task text to preserve its scope;
    # this preamble pins the backend and explains this native path translation.
    instruction = ("Native adapter has selected and verified the DuckDB backend (DB_TYPE=duckdb). "
                   "Use this project's existing profiles.yml; no shell tool is exposed, so the adapter replaces "
                   "the original echo-DB_TYPE setup step. Read/edit tool paths are relative to the task workspace.\n") + instruction
    (case_dir / "instruction.md").write_text(instruction, encoding="utf-8")
    metadata = {"task_id": task_id, "upstream_commit": PINNED_COMMIT, "mode": "native-adapted-public-development-case",
                "project_dir": str(project), "database_path": str(database_dir / "retail.duckdb"), "model": PUBLIC_TASK_MODELS[task_id],
                "initialized": initialize, "task_type": "create-model" if create_model else "fix-model", "initialization_selectors": list(selectors),
                "bug_overlay": overlay,
                "base_build": "all models" if full_base_build else ("declared staging inputs and ancestors" if create_model else "selected model and ancestors"),
                "runtime": runtime_versions(), "path_translations": {"/app/dbt_models_duckdb": str(project), "/app/database/retail.duckdb": str(database_dir / "retail.duckdb")},
                "official_harbor_result": False, "hidden_verifier_used_by_agent": False}
    if duckdb_timezone is not None:
        metadata["runtime_settings"] = {"duckdb_timezone": duckdb_timezone}
        metadata["runtime"]["duckdb_timezone"] = duckdb_timezone
    if package_adaptation is not None:
        metadata["runtime_adaptations"] = {"packages_cache": package_adaptation}
    (case_dir / "native-case.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def evaluate_native_case(case_dir: Path, evaluator_root: Path, *, grading_protocol: str | None = None) -> dict:
    """Run upstream's original verifier once, after agent execution has stopped.

    Test text changes only absolute paths. An optional declared UTC session
    setting uses a separately archived launcher; assertions remain unchanged.
    The evaluator directory must remain outside the agent case.
    """
    case_dir, evaluator_root = case_dir.resolve(), evaluator_root.resolve()
    if evaluator_root == case_dir or case_dir in evaluator_root.parents:
        raise ValueError("Verifier directory must be outside the agent's case directory")
    meta = json.loads((case_dir / "native-case.json").read_text(encoding="utf-8"))
    if meta["upstream_commit"] != PINNED_COMMIT or meta["task_id"] not in PUBLIC_TASK_MODELS:
        raise ValueError("Unexpected native case revision/task")
    task_id = meta["task_id"]
    if task_id in EXPLICIT_GRADING_TASKS:
        if grading_protocol not in ("pytest_exit_status", "component_reward_json"):
            raise ValueError("This new task requires an explicit grading_protocol after reviewing its original harness")
    elif grading_protocol is not None:
        raise ValueError("grading_protocol overrides are only supported for the explicitly registered new task")
    evaluator_dir = evaluator_root / task_id
    evaluator_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://raw.githubusercontent.com/{REPOSITORY}/{PINNED_COMMIT}/tasks/{task_id}/tests/test_outputs.py"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "DataPatch-final-evaluator/0.1"}), timeout=90) as response:
        source = response.read()
    (evaluator_dir / "test_outputs.original.py").write_bytes(source)
    verifier_logs = evaluator_dir / (case_dir.name + "-logs")
    adapted = source.decode("utf-8").replace("/app/dbt_models_duckdb", (case_dir / "project").as_posix()).replace("/app/database/retail.duckdb", (case_dir / "database/retail.duckdb").as_posix()).replace("/logs/verifier", verifier_logs.as_posix())
    evaluator = evaluator_dir / ("test_outputs_" + re.sub(r"[^A-Za-z0-9_]", "_", case_dir.name) + ".py")
    evaluator.write_bytes(adapted.encode("utf-8"))
    ordinary_pytest = grading_protocol == "pytest_exit_status" if task_id in EXPLICIT_GRADING_TASKS else task_id in PYTEST_EXIT_STATUS_TASKS
    scoring = {}
    if ordinary_pytest or task_id in EXPLICIT_GRADING_TASKS:
        scoring_url = f"https://raw.githubusercontent.com/{REPOSITORY}/{PINNED_COMMIT}/tasks/{task_id}/tests/test.sh"
        with urllib.request.urlopen(urllib.request.Request(scoring_url, headers={"User-Agent": "DataPatch-final-evaluator/0.1"}), timeout=90) as response:
            scoring_source = response.read()
        (evaluator_dir / "test.original.sh").write_bytes(scoring_source)
        if task_id in EXPLICIT_GRADING_TASKS:
            scoring["grading_protocol_selection"] = "explicit_operator_selection_after_solver_stopped"
        scoring = {"scoring_source": scoring_url, "scoring_source_sha256": hashlib.sha256(scoring_source).hexdigest(),
                   "harness_execution": ("native Python equivalent of pinned shell exit/count grading; test assertions unchanged" if ordinary_pytest
                                         else "original pytest verifier reward.json; protocol explicitly selected after original harness review; test assertions unchanged"),
                   **scoring}
    options = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT} if ordinary_pytest else {"capture_output": True}
    flags = ["-v"] if ordinary_pytest else ["-q", "-s"]
    command = [sys.executable, "-m", "pytest", *flags, str(evaluator)]
    runtime_evidence = {}
    duckdb_timezone = meta.get("runtime_settings", {}).get("duckdb_timezone")
    if duckdb_timezone not in (None, "UTC"):
        raise ValueError("Explicit DuckDB timezone must be UTC or omitted")
    if duckdb_timezone is not None:
        launcher = Path(__file__).resolve().with_name("run_public_pytest.py")
        launcher_archive = evaluator_dir / "run_public_pytest.py"
        launcher_bytes = launcher.read_bytes()
        launcher_archive.write_bytes(launcher_bytes)
        command = [sys.executable, str(launcher_archive), "--duckdb-timezone", duckdb_timezone, *flags, str(evaluator)]
        runtime_evidence = {"runtime_settings": {"duckdb_timezone": duckdb_timezone},
                            "runtime_launcher": {"source_path": str(launcher), "archive_path": str(launcher_archive),
                                                 "sha256": hashlib.sha256(launcher_bytes).hexdigest(),
                                                 "scope": "Declared DuckDB connection session setting; pytest assertions and exit status unchanged"},
                            "command": command}
    result = subprocess.run(command, cwd=evaluator_dir, env=native_environment(case_dir), **options, text=True, encoding="utf-8", errors="replace", timeout=3000)
    reward_path = verifier_logs / "reward.json"
    reward = json.loads(reward_path.read_text(encoding="utf-8")).get("reward") if reward_path.exists() else None
    passed = re.findall(r"^PASS: (component_\w+)", result.stdout, re.M)
    failed = re.findall(r"^FAIL: (component_\w+)", result.stdout, re.M)
    returncode = result.returncode
    if ordinary_pytest:
        counts = pytest_counts(result.stdout)
        reward = pytest_exit_reward(result.returncode, counts)
        returncode = 0 if reward == 1 else 1
        verifier_logs.mkdir(parents=True, exist_ok=True)
        (verifier_logs / "reward.txt").write_text(str(int(reward)) + "\n", encoding="utf-8")
        scoring.update({"pytest_counts": counts, "pytest_returncode": result.returncode})
    report = {"task_id": task_id, "mode": "native-path-adapted-upstream-verifier", "official_harbor_result": False,
              "upstream_commit": PINNED_COMMIT, "source_url": url, "original_sha256": hashlib.sha256(source).hexdigest(),
              "adapted_sha256": hashlib.sha256(adapted.encode()).hexdigest(), "path_translation_only": True,
              "returncode": returncode, "reward": reward, "components_passed": passed, "components_failed": failed,
              "grading_protocol": "pytest_exit_status" if ordinary_pytest else "component_reward_json", **scoring,
              **runtime_evidence,
              "stdout": result.stdout, "stderr": result.stderr or ""}
    if meta.get("runtime_adaptations"):
        report["runtime_adaptations"] = meta["runtime_adaptations"]
    output = evaluator_dir / f"{case_dir.name}-evaluation.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return {"report": str(output), "returncode": returncode, "reward": reward, "components_passed": len(passed), "components_failed": len(failed), "stdout_tail": result.stdout[-2500:]}


def install_public_contracts(case_dir: Path, contracts_dir: Path | None) -> dict | None:
    """Install caller-supplied visible business checks without changing task text.

    This is project configuration, not benchmark verifier or reference SQL.
    Only root SQL files and an optional short README enter the solver workspace.
    Existing different content is rejected; matching files are left untouched.
    """
    if contracts_dir is None:
        return None
    case_dir, contracts_dir = case_dir.resolve(), contracts_dir.resolve()
    if not contracts_dir.is_dir():
        raise ValueError("Public contracts directory does not exist")
    original_path = case_dir / "instruction.md"
    instruction = original_path.read_text(encoding="utf-8")
    sources = sorted(path for path in contracts_dir.glob("*.sql") if path.is_file())
    readme_source = contracts_dir / "README.md"
    readme_text = None
    if readme_source.is_file():
        readme_text = readme_source.read_bytes().decode("utf-8-sig")
        if len(readme_text) > 6000:
            raise ValueError("Public contract README.md must contain at most 6000 characters")
        sources.append(readme_source)
    planned = [(source, case_dir / "checks" / source.name, source.read_bytes()) for source in sources]
    for _, destination, data in planned:
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError(f"Public contract would overwrite existing content: {destination.name}")
    files = []
    for source, destination, data in planned:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            destination.write_bytes(data)
        files.append({"kind": "readme" if source.name == "README.md" else "sql",
                      "source": str(source), "path": str(destination),
                      "source_sha256": hashlib.sha256(data).hexdigest(),
                      "installed_sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
    suffix = ("\n\nProject-provided public business contract\n"
              "Origin: project_configuration. These visible checks are project requirements, "
              "not hidden tests or reference answers. Use check_contracts to execute checks/*.sql.\n")
    if readme_text is not None:
        suffix += "\n" + readme_text
    instruction_path = case_dir / "solver-instruction.md"
    instruction_path.write_bytes((instruction + suffix).encode("utf-8"))
    return {"contract_origin": "project_configuration", "hidden_tests": False, "reference_solution": False,
            "source_directory": str(contracts_dir), "files": files,
            "original_instruction_path": str(original_path),
            "original_instruction_sha256": hashlib.sha256(original_path.read_bytes()).hexdigest(),
            "instruction_path": str(instruction_path),
            "instruction_sha256": hashlib.sha256(instruction_path.read_bytes()).hexdigest()}


def run_native_case(case_dir: Path, result_root: Path, *, mode: str = "verified", max_steps: int | None = None, budget_usd: float | None = None, source_snapshot: Path | None = None, contracts_dir: Path | None = None) -> dict:
    """Execute DataPatch only; upstream verifier results never enter its context."""
    from datapatch.agent import Agent, AGENT_REVISION
    from datapatch.config import Settings
    from datapatch.evaluation import source_digest
    from datapatch.workspace import Workspace

    case_dir, result_root = case_dir.resolve(), result_root.resolve()
    if result_root == case_dir or case_dir in result_root.parents:
        raise ValueError("Result directory must be outside the agent's case directory")
    meta = json.loads((case_dir / "native-case.json").read_text(encoding="utf-8"))
    if not meta["initialized"]:
        raise ValueError("Initialize the dbt ancestors before asking the agent to run")
    result_root.mkdir(parents=True, exist_ok=True)
    prefix = result_root / f"{case_dir.name}-{mode}"
    if prefix.with_suffix(".json").exists():
        raise ValueError("A result already exists; each independent trial needs a fresh prepared case")
    public_contracts = install_public_contracts(case_dir, contracts_dir)
    instruction_path = Path(public_contracts["instruction_path"]) if public_contracts else case_dir / "instruction.md"
    target_path = case_dir / "project" / PUBLIC_TASK_MODELS[meta["task_id"]]
    target_start = {"path": str(target_path), "exists": target_path.is_file(),
                    "sha256": hashlib.sha256(target_path.read_bytes()).hexdigest() if target_path.is_file() else None}
    config = Settings.load()
    if max_steps is not None:
        config.max_steps = max_steps
    if budget_usd is not None:
        config.run_budget_usd = budget_usd
    duckdb_timezone = meta.get("runtime_settings", {}).get("duckdb_timezone")
    workspace_options = {"duckdb_timezone": duckdb_timezone} if duckdb_timezone is not None else {}
    workspace = Workspace(case_dir, project_dir=case_dir / "project", database_path=case_dir / "database/retail.duckdb", **workspace_options)
    # Preparation has already materialized the declared ancestors. Acceptance
    # targets this ticket's model, not unrelated upstream source-quality tests.
    workspace.default_select = Path(PUBLIC_TASK_MODELS[meta["task_id"]]).stem
    event_path = prefix.with_suffix(".jsonl")
    observed_model_versions: list[str] = []
    core_source_sha256 = source_digest()
    snapshot_sha256 = None
    if source_snapshot is not None:
        source_snapshot = source_snapshot.resolve()
        with zipfile.ZipFile(source_snapshot) as archive:
            manifest = json.loads(archive.read("source-manifest.json"))
        if manifest["core_source_sha256"] != core_source_sha256:
            raise ValueError("Source snapshot does not match the current core; freeze the implementation before running")
        snapshot_sha256 = hashlib.sha256(source_snapshot.read_bytes()).hexdigest()
    with event_path.open("w", encoding="utf-8") as events:
        def emit(event: dict) -> None:
            events.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            events.flush()
            if event.get("type") == "tool":
                print(f"tool {event.get('name')} step={event.get('step')}", flush=True)
            elif event.get("type") == "model":
                version = event.get("name")
                if isinstance(version, str) and version and version not in observed_model_versions:
                    observed_model_versions.append(version)
                print(f"model call tokens={event.get('usage', {}).get('total_tokens', '?')}", flush=True)
        agent = Agent(workspace, config, mode=mode, emit=emit, focus_model=Path(PUBLIC_TASK_MODELS[meta["task_id"]]).stem)
        agent_started = time.monotonic()
        try:
            result = agent.run(instruction_path.read_text(encoding="utf-8"))
        except Exception as exc:
            result = {"error": str(exc), "error_type": type(exc).__name__, "metrics": agent.metrics}
        finally:
            result.setdefault("metrics", {}).setdefault("elapsed_seconds", round(time.monotonic() - agent_started, 3))
    # Independent acceptance evidence, never appended to the model transcript.
    try:
        final_build = workspace.run_dbt("build")
        final_build = verify_target_build(final_build, workspace.project_dir, PUBLIC_TASK_MODELS[meta["task_id"]])
    except Exception as exc:
        final_build = {"success": False, "error": str(exc), "error_type": type(exc).__name__}
    report = {"benchmark": "data-eng-bench", "task_id": meta["task_id"], "commit": meta["upstream_commit"],
              "mode": mode, "model": config.model, "max_steps": config.max_steps, "budget_usd": config.run_budget_usd,
              "generation_settings": {"thinking_enabled": config.thinking_enabled, "reasoning_effort": config.reasoning_effort, "max_output_tokens": config.max_output_tokens,
                                      "input_usd_per_million_tokens": config.input_rate, "output_usd_per_million_tokens": config.output_rate},
              "observed_model_versions": observed_model_versions,
              "instruction_path": str(instruction_path), "public_contracts": public_contracts, "target_start": target_start,
              "acceptance_select": workspace.default_select,
              "source_sha256": core_source_sha256,
              "agent_revision": AGENT_REVISION,
              "source_snapshot": str(source_snapshot) if source_snapshot is not None else None,
              "source_snapshot_sha256": snapshot_sha256,
              "setting": meta["mode"], "official_harbor_result": False, "result": result, "final_build": final_build, "events": str(event_path)}
    if duckdb_timezone is not None:
        report["runtime_settings"] = {"duckdb_timezone": duckdb_timezone}
    if meta.get("runtime_adaptations"):
        report["runtime_adaptations"] = meta["runtime_adaptations"]
    prefix.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    prefix.with_suffix(".patch").write_text(workspace.diff(), encoding="utf-8")
    return {"report": str(prefix.with_suffix('.json')), "result": result}


def render_public_summary(case_dir: Path, result_root: Path, evaluator_root: Path, output: Path, *, mode: str = "verified", planned_tasks: tuple[str, ...] | None = None, repeat: int = 0, repeats: int | None = None) -> dict:
    """Package actual native results for the same reports UI as local evaluations."""
    from datapatch.evaluation import render_report, summarize

    case_dir = case_dir.resolve()
    meta = json.loads((case_dir / "native-case.json").read_text(encoding="utf-8"))
    agent_path = result_root / f"{case_dir.name}-{mode}.json"
    verifier_path = evaluator_root / meta["task_id"] / f"{case_dir.name}-evaluation.json"
    agent_report = json.loads(agent_path.read_text(encoding="utf-8"))
    verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
    previous = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    previous_protocol = previous.get("protocol") or {}
    frozen_tasks = tuple(previous_protocol.get("planned_task_ids") or LEGACY_TASKS)
    selected_tasks = tuple(planned_tasks) if planned_tasks is not None else frozen_tasks
    planned_repeats = repeats if repeats is not None else previous_protocol.get("repeats", 1)
    if not selected_tasks or len(selected_tasks) != len(set(selected_tasks)) or any(task not in PUBLIC_TASK_MODELS for task in selected_tasks):
        raise ValueError("Report requires a nonempty, unique subset of supported tasks")
    if previous and selected_tasks != frozen_tasks:
        raise ValueError("Existing report task plan is frozen; use a new output for a new protocol")
    if not isinstance(planned_repeats, int) or isinstance(planned_repeats, bool) or planned_repeats < 1 or not isinstance(repeat, int) or isinstance(repeat, bool) or not 0 <= repeat < planned_repeats:
        raise ValueError("repeat must belong to a positive planned repeats range")
    if previous and planned_repeats != previous_protocol.get("repeats", 1):
        raise ValueError("Existing report repeat plan is frozen; use a new output for a new protocol")
    if meta["task_id"] not in selected_tasks:
        raise ValueError("Task is outside the report's fixed planned subset")
    pytest_executed = bool(re.search(r"\b[1-9]\d* (?:passed|failed)\b[^\n]*\bin \d+(?:\.\d+)?s\b", verifier.get("stdout", "")))
    ordinary_pytest = verifier.get("grading_protocol") == "pytest_exit_status"
    counts = verifier.get("pytest_counts") or {}
    valid_test_execution = pytest_executed and (counts.get("passed", 0) + counts.get("failed", 0) > 0 if ordinary_pytest else bool(verifier.get("components_passed") or verifier.get("components_failed"))) and verifier.get("reward") is not None
    execution_failed = bool(agent_report["result"].get("error"))
    final_build = agent_report.get("final_build")
    if not isinstance(final_build, dict):
        final_build = {"success": "component_1_model_compiles" in verifier.get("components_passed", []), "evidence": "legacy upstream compilation component; no separate final build was recorded"}
    grading_passed = (pytest_exit_reward(verifier.get("pytest_returncode", verifier["returncode"]), counts) == 1 if ordinary_pytest
                      else bool(verifier.get("components_passed")) and not verifier.get("components_failed"))
    passed = valid_test_execution and not execution_failed and final_build.get("success") is True and verifier["reward"] == 1.0 and verifier["returncode"] == 0 and grading_passed
    record = {"run_id": f"{case_dir.name}-{mode}", "task_id": meta["task_id"], "mode": mode, "repeat": repeat,
              "status": "completed" if valid_test_execution and not execution_failed else "failed", "metrics": agent_report["result"].get("metrics", {}),
              "model": agent_report["model"], "max_steps": agent_report["max_steps"], "budget_usd": agent_report["budget_usd"],
              "generation_settings": agent_report.get("generation_settings"), "observed_model_versions": agent_report.get("observed_model_versions", []),
              "instruction_path": agent_report.get("instruction_path"), "public_contracts": agent_report.get("public_contracts"), "target_start": agent_report.get("target_start"),
              "source_sha256": agent_report.get("source_sha256"),
              "agent_revision": agent_report.get("agent_revision"),
              "source_snapshot": agent_report.get("source_snapshot"), "source_snapshot_sha256": agent_report.get("source_snapshot_sha256"),
              "stop_reason": agent_report["result"].get("stop_reason"), "final_answer": agent_report["result"].get("final_answer", ""),
              "candidate_review": agent_report["result"].get("candidate_review"),
              "execution_error": agent_report["result"].get("error"), "execution_error_type": agent_report["result"].get("error_type"),
              "verification": {"passed": bool(passed), "reward": verifier.get("reward"), "components_passed": verifier.get("components_passed", []), "components_failed": verifier.get("components_failed", []), "valid_pytest_execution": valid_test_execution,
                               "grading_protocol": verifier.get("grading_protocol", "component_reward_json"), "pytest_counts": verifier.get("pytest_counts")},
              "final_build": final_build,
              "agent_report": str(agent_path.resolve()), "verifier_report": str(verifier_path.resolve()), "raw_verifier": verifier}
    records = [row for row in previous.get("records", []) if row["run_id"] != record["run_id"]]
    for row in records:
        row.setdefault("max_steps", previous.get("protocol", {}).get("max_steps"))
    records.append(record)
    combinations = [(row["task_id"], row["mode"], row.get("repeat", 0)) for row in records]
    if any(count > 1 for count in Counter(combinations).values()):
        raise ValueError("Duplicate task/mode/repeat combination; record independent repeats with distinct repeat numbers")
    modes = list(dict.fromkeys(row["mode"] for row in records))
    planned_trials = len(selected_tasks) * len(modes) * planned_repeats
    expected = {(task, selected_mode, trial) for task in selected_tasks for selected_mode in modes for trial in range(planned_repeats)}
    report = {"name": output.stem, "title": "data-eng-bench 公开开发任务：本地适配实际结果（非官方成绩）",
              "created_at": datetime.now(timezone.utc).isoformat(), "dataset": "snowflake-data-eng-bench/native-public-development-subset",
              "provenance": "Snowflake-Labs/data-eng-bench 固定公开开发题；原始数据、dbt项目和任务说明，Windows native路径适配；非官方Docker/Harbor成绩，非未知保留集。",
              "upstream_repository": f"https://github.com/{REPOSITORY}", "upstream_commit": PINNED_COMMIT, "official_harbor_result": False,
              "protocol": {"task_ids": list(dict.fromkeys(row["task_id"] for row in records)), "planned_task_ids": list(selected_tasks), "modes": modes, "repeats": planned_repeats, "model": agent_report["model"],
                           "max_steps_by_task": {row["task_id"]: row.get("max_steps") for row in records}, "budget_usd": agent_report["budget_usd"], "hidden_feedback_to_agent": False,
                           "source_sha256_by_trial": {row["run_id"]: row.get("source_sha256") for row in records},
                           "agent_revision_by_trial": {row["run_id"]: row.get("agent_revision") for row in records},
                           "generation_settings_by_trial": {row["run_id"]: row.get("generation_settings") for row in records},
                           "observed_model_versions_by_trial": {row["run_id"]: row.get("observed_model_versions", []) for row in records},
                           "cost_is_estimate": True, "path_translation_only_in_verifier": True, "base_build": meta["base_build"], "runtime": meta["runtime"],
                           "initial_adapter_issue": "A direct Python invocation only defined test functions; it was not counted as a score. This report uses the subsequent actual pytest execution."},
              "limitations": [f"Only {len(records)} public development trial(s) in a fixed task subset; no performance/generalization claim.",
                              "Native Windows/dbt versions and selected-ancestor initialization differ from the official Linux Docker environment.",
                              "Task success requires every upstream component to pass; partial component credit is descriptive only.",
                              "No React comparison was run; these are development executions rather than an ablation experiment."],
              "status": "completed" if len(records) == planned_trials and set(combinations) == expected else "running", "planned_trials": planned_trials, "records": records, "summary": summarize(records)}
    if any(row.get("public_contracts") for row in records):
        report["protocol"]["assistance"] = "project_public_business_contract"
        report["protocol"]["public_contracts_by_trial"] = {row["run_id"]: row.get("public_contracts") for row in records}
        report["protocol"]["instruction_path_by_trial"] = {row["run_id"]: row.get("instruction_path") for row in records}
        report["protocol"]["target_start_by_trial"] = {row["run_id"]: row.get("target_start") for row in records}
        report["limitations"].append("Explicit project-provided public business contracts assisted this execution; this is not an unassisted original-ticket or official benchmark result. Target starting hashes identify any preloaded repair continuation.")
    if any(row.get("stop_reason") == "step_limit" for row in records):
        report["limitations"].append("At least one execution reached the model step limit; inspect per-trial action logs before claiming completed delivery.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    render_report(report, output.with_suffix(".md"))
    with output.with_suffix(".md").open("a", encoding="utf-8") as markdown:
        markdown.write("\n## 外部任务验收与限制\n\n")
        markdown.write(f"固定 commit：`{PINNED_COMMIT}`；模型：`{agent_report['model']}`。\n\n")
        markdown.write("| 任务 | 最大步数 | 停止原因 | 上游组件通过/总数 | 二元reward |\n|---|---:|---|---:|---:|\n")
        for row in records:
            verification = row["verification"]
            component_count = len(verification["components_passed"]) + len(verification["components_failed"])
            unit_result = f"{len(verification['components_passed'])}/{component_count} components"
            if verification.get("grading_protocol") == "pytest_exit_status":
                unit_counts = verification.get("pytest_counts") or {}
                unit_result = f"{unit_counts.get('passed', 0)} passed / {unit_counts.get('failed', 0)} failed tests"
            markdown.write(f"| {row['task_id']} | {row.get('max_steps')} | {row['stop_reason']} | {unit_result} | {verification['reward']} |\n")
        markdown.write("\n")
        for limitation in report["limitations"]:
            markdown.write(f"- {limitation}\n")
        for row in records:
            markdown.write("\n### " + row["task_id"] + "\n\n原始 pytest 输出（只进行路径重映射，未改测试断言）：\n\n```text\n" + row["raw_verifier"]["stdout"] + "\n```\n")
    return {"report": str(output.resolve()), "summary": report["summary"], "valid_pytest_execution": valid_test_execution}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--snapshot", type=Path, default=Path("external/data-eng-bench"))
    prepare.add_argument("--case", type=Path, required=True)
    prepare.add_argument("--task", choices=PUBLIC_TASK_MODELS, default="dbt-fix-refund-reconciliation")
    prepare.add_argument("--skip-initialize", action="store_true")
    prepare.add_argument("--full-base-build", action="store_true")
    prepare.add_argument("--duckdb-timezone", choices=("UTC",), help="Explicit DuckDB/dbt and verifier session timezone; omitted preserves native defaults")
    prepare.add_argument("--packages-cache", type=Path, help="Verified pinned dbt_utils cache; runtime local path avoids registry resolution")
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--case", type=Path, required=True)
    evaluate.add_argument("--evaluator-root", type=Path, default=Path("external/public-verifiers"))
    evaluate.add_argument("--grading-protocol", choices=("pytest_exit_status", "component_reward_json"),
                          help="Required only for the newly registered task, after solver completion and original harness review")
    run = sub.add_parser("run")
    run.add_argument("--case", type=Path, required=True)
    run.add_argument("--result-root", type=Path, default=Path("external/native-results"))
    run.add_argument("--mode", choices=("baseline", "react", "context", "verified"), default="verified")
    run.add_argument("--max-steps", type=int)
    run.add_argument("--budget-usd", type=float, help="Override this run only; does not modify shared .env")
    run.add_argument("--source-snapshot", type=Path, help="Source zip whose manifest must match the current core")
    run.add_argument("--contracts-dir", type=Path, help="Project-provided root SQL business checks and optional README.md; not hidden tests")
    report = sub.add_parser("report")
    report.add_argument("--case", type=Path, required=True)
    report.add_argument("--result-root", type=Path, default=Path("external/native-results"))
    report.add_argument("--evaluator-root", type=Path, default=Path("external/public-verifiers"))
    report.add_argument("--mode", default="verified")
    report.add_argument("--output", type=Path, default=Path("artifacts/evaluations/public_native_subset_20261025.json"))
    report.add_argument("--planned-task", action="append", choices=PUBLIC_TASK_MODELS, help="Repeat to freeze the report task subset; default preserves the historical two")
    report.add_argument("--repeat", type=int, default=0, help="Zero-based independent trial number")
    report.add_argument("--repeats", type=int, help="Planned repeats per task; fixed when creating a new report")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_native_case(args.snapshot, args.case, args.task, initialize=not args.skip_initialize, full_base_build=args.full_base_build, duckdb_timezone=args.duckdb_timezone, packages_cache=args.packages_cache)
    elif args.command == "evaluate":
        result = evaluate_native_case(args.case, args.evaluator_root, grading_protocol=args.grading_protocol)
    elif args.command == "run":
        result = run_native_case(args.case, args.result_root, mode=args.mode, max_steps=args.max_steps, budget_usd=args.budget_usd, source_snapshot=args.source_snapshot, contracts_dir=args.contracts_dir)
    else:
        result = render_public_summary(args.case, args.result_root, args.evaluator_root, args.output, mode=args.mode, planned_tasks=tuple(args.planned_task) if args.planned_task else None, repeat=args.repeat, repeats=args.repeats)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
