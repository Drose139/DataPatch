"""Persistent runs shared by the CLI and FastAPI UI."""
from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .agent import Agent, MODES
from .config import Settings
from .evidence import capture_output, compare_outputs
from .fixtures import create_task, list_tasks, verify_task
from .workspace import Workspace


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # Windows readers/antivirus can briefly hold the destination without delete
    # sharing. Retry this observed sharing violation; do not repeat model calls.
    for attempt in range(8):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.02 * min(2 ** attempt, 8))


class RunService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.load()
        self.runs_dir = self.settings.artifacts_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="datapatch")
        self.lock = threading.RLock()

    def tasks(self) -> list[dict]:
        return list_tasks()

    def task_detail(self, task_id: str) -> dict:
        task = next((task for task in list_tasks() if task["id"] == task_id), None)
        if not task:
            raise KeyError(task_id)
        return task

    def config_status(self) -> dict:
        settings = Settings.load()
        return {"api_key_configured": bool(settings.api_key), "model": settings.model, "thinking_enabled": settings.thinking_enabled, "reasoning_effort": settings.reasoning_effort, "container_available": shutil.which("docker") is not None, "execution_backend": "native_trusted", "estimated_run_budget_usd": settings.run_budget_usd, "modes": list(MODES)}

    def _path(self, run_id: str) -> Path:
        if not run_id or any(c not in "0123456789abcdef-" for c in run_id):
            raise KeyError(run_id)
        return self.runs_dir / run_id / "run.json"

    def get_run(self, run_id: str) -> dict:
        with self.lock:
            return json.loads(self._path(run_id).read_text(encoding="utf-8"))

    def list_runs(self) -> list[dict]:
        runs = []
        with self.lock:
            for path in sorted(self.runs_dir.glob("*/run.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    runs.append({k: v for k, v in record.items() if k not in {"events", "diff", "initial_snapshot"}})
                except (OSError, ValueError):
                    continue
        return runs

    def _new(self, task_id: str, mode: str, provider: str, max_steps: int | None) -> dict:
        task = self.task_detail(task_id)
        if mode not in MODES:
            raise ValueError("不支持的 mode")
        if provider != "deepseek":
            raise ValueError("运行仅支持真实 deepseek；已有运行可直接回放")
        settings = Settings.load()
        if not settings.api_key:
            raise ValueError("请先在 .env 中配置 DEEPSEEK_API_KEY")
        run_id = str(uuid.uuid4())
        record = {"run_id": run_id, "task_id": task_id, "task": task, "mode": mode, "provider": provider, "status": "queued", "started_at": now(), "finished_at": None, "model": settings.model, "execution_backend": "native_trusted", "events": [], "metrics": {}, "diff": "", "checks": [], "verification": None, "final_answer": "", "max_steps": max_steps or settings.max_steps}
        write_json(self._path(run_id), record)
        return record

    def start_run(self, task_id: str, mode: str = "verified", provider: str = "deepseek", max_steps: int = 12) -> dict:
        record = self._new(task_id, mode, provider, max_steps)
        self.pool.submit(self._execute, record["run_id"])
        return {"run_id": record["run_id"], "status": "queued"}

    def run_sync(self, task_id: str, mode: str = "verified", max_steps: int | None = None) -> dict:
        record = self._new(task_id, mode, "deepseek", max_steps)
        self._execute(record["run_id"])
        return self.get_run(record["run_id"])

    def _execute(self, run_id: str) -> None:
        record = self.get_run(run_id)
        started = time.monotonic()
        directory = self._path(run_id).parent
        workspace = directory / "workspace"

        def emit(event: dict) -> None:
            with self.lock:
                item = {"seq": len(record["events"]) + 1, "timestamp": now(), **event}
                record["events"].append(item)
                if event.get("metrics"):
                    record["metrics"].update(event["metrics"])
                with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
                write_json(self._path(run_id), record)

        tool_workspace = None
        try:
            record["status"] = "running"
            metadata = create_task(record["task_id"], workspace)
            database_path = Path(metadata.get("database_path", workspace / "warehouse.duckdb"))
            tool_workspace = Workspace(workspace, database_path=database_path)
            record["workspace"] = str(workspace)
            record["task_metadata"] = metadata
            emit({"type": "status", "content": "初始化独立任务数据并构建初始模型"})
            seed_result = tool_workspace.run_dbt("seed")
            if not seed_result["success"]:
                raise RuntimeError("任务种子初始化失败: " + json.dumps(seed_result, ensure_ascii=False)[-5000:])
            initial = tool_workspace.run_dbt("run")
            record["initial_build"] = initial
            before = capture_output(database_path, metadata.get("output_table", ""), metadata.get("key_columns"))
            try:
                record["initial_checks"] = tool_workspace.check_contracts()
            except Exception as exc:
                record["initial_checks"] = {"error": str(exc)}
            emit({"type": "status", "content": "Agent 开始执行工单", "result": {"initial_build_success": initial["success"], "initial_checks": record["initial_checks"]}})
            settings = Settings.load()
            settings.max_steps = max(1, min(int(record["max_steps"]), 40))
            agent = Agent(tool_workspace, settings, mode=record["mode"], emit=emit)
            result = agent.run(record["task"]["description"])
            record.update({key: value for key, value in result.items() if key != "metrics"})
            record["metrics"].update(result["metrics"])
            # All conditions get the same final materialization and hidden evaluator.
            # These results are not fed back to the agent.
            final_build = tool_workspace.run_dbt("build")
            record["final_build"] = final_build
            after = capture_output(database_path, metadata.get("output_table", ""), metadata.get("key_columns"))
            record["data_evidence"] = {
                "before": before, "after": after, "comparison": compare_outputs(before, after),
                "initial_build_success": bool(initial.get("success")),
                "final_build_success": bool(final_build.get("success")),
                "contracts_before": record.get("initial_checks"),
                "contracts_after": tool_workspace.check_contracts(),
                "note": "Observed data changes are evidence, not a correctness score. A failed build can leave stale tables.",
            }
            write_json(directory / "data_evidence.json", record["data_evidence"])
            emit({"type": "status", "content": "Agent 已停止，开始独立最终验收（不会回传模型）"})
            oracle_verification = verify_task(record["task_id"], workspace)
            # A failed build may leave a previously correct materialized table.
            # Grade the submitted patch as well as those persisted output rows.
            build_passed = bool(final_build.get("success"))
            verification = {
                **oracle_verification,
                "passed": build_passed and bool(oracle_verification.get("passed")),
                "checks": [
                    {"name": "final_build_success", "passed": build_passed,
                     "expected": True, "actual": build_passed},
                    *oracle_verification.get("checks", []),
                ],
            }
            if not build_passed:
                verification["summary"] = (
                    "Final build failed; matching output may be from stale tables. "
                    "Independent output checks: " + str(oracle_verification.get("summary", ""))
                )
            record["verification"] = verification
            record["checks"] = verification.get("checks", [])
            record["diff"] = tool_workspace.diff()
            (directory / "patch.diff").write_text(record["diff"], encoding="utf-8")
            write_json(directory / "verification.json", verification)
            record["status"] = "completed"
            emit({"type": "validation", "name": "independent_final_evaluator", "result": verification})
        except Exception as exc:
            record["status"] = "failed"
            # Provider errors have already had credentials removed.
            record["error"] = f"{type(exc).__name__}: {str(exc)[:6000]}"
            if record.get("verification"):
                previous = record["verification"]
                record["verification"] = {
                    **previous, "passed": False,
                    "summary": "Execution failed after output verification: " + record["error"],
                    "checks": [{"name": "execution_completed", "passed": False,
                                "expected": True, "actual": False}, *previous.get("checks", [])],
                }
                record["checks"] = record["verification"]["checks"]
                write_json(directory / "verification.json", record["verification"])
            if tool_workspace:
                record["diff"] = tool_workspace.diff()
            emit({"type": "error", "content": record["error"]})
        finally:
            record["finished_at"] = now()
            record["metrics"]["elapsed_seconds"] = round(time.monotonic() - started, 3)
            with self.lock:
                write_json(self._path(run_id), record)

    def reports(self) -> list[dict]:
        directory = self.settings.artifacts_dir / "evaluations"
        result = []
        for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                title = data.get("title", path.stem)
                if path.stem not in title:
                    title += " · " + path.stem
                if path.stem.endswith("_unamended"):
                    title = "历史原报告（修订前）· " + title
                result.append({"name": path.stem, "title": title, "summary": data.get("summary"), "created_at": data.get("created_at"), "dataset": data.get("dataset")})
            except (OSError, ValueError):
                continue
        return result

    def read_report(self, name: str) -> dict:
        if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in name):
            raise KeyError(name)
        return json.loads((self.settings.artifacts_dir / "evaluations" / f"{name}.json").read_text(encoding="utf-8"))
