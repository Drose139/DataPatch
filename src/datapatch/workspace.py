"""Bounded tools for an individual task workspace.

Native execution is for the bundled trusted SQL projects. It is not an OS sandbox.
No shell tool, network tool, reference patch, or evaluator is exposed to the model.
"""
from __future__ import annotations

import difflib
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import duckdb
from jinja2 import Environment, StrictUndefined


class Workspace:
    def __init__(self, root: Path, project_dir: Path | None = None, database_path: Path | None = None, *, duckdb_timezone: str | None = None):
        if duckdb_timezone not in (None, "UTC"):
            raise ValueError("Explicit DuckDB timezone must be UTC or omitted")
        self.root = root.resolve()
        self.project_dir = (project_dir or self.root).resolve()
        self.database_path = (database_path or self.root / "warehouse.duckdb").resolve()
        self.duckdb_timezone = duckdb_timezone
        self.default_select: str | None = None
        self.original = {str(p.relative_to(self.root)).replace("\\", "/"): p.read_text(encoding="utf-8") for p in self.project_dir.glob("models/**/*.sql")}

    def _path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("路径必须位于当前任务工作区内")
        if any(part.startswith(".") for part in Path(relative).parts):
            raise ValueError("工具不能读取隐藏文件")
        return path

    def list_files(self, directory: str = ".") -> dict:
        directory_path = self.root if directory == "." else self._path(directory)
        files = []
        for path in sorted(directory_path.rglob("*")):
            relative = path.relative_to(self.root)
            if path.is_file() and path.suffix in (".sql", ".yml", ".yaml", ".md", ".csv") and not set(relative.parts) & {"target", "logs", "dbt_packages"}:
                files.append(str(relative).replace("\\", "/"))
        return {"files": files[:150], "truncated": len(files) > 150}

    def read_file(self, path: str) -> dict:
        file_path = self._path(path)
        if file_path.suffix not in {".sql", ".yml", ".yaml", ".md", ".csv", ".json"}:
            raise ValueError("只允许读取项目文本文件")
        if file_path.stat().st_size > 300_000:
            raise ValueError("文件较大，请使用 SQL 查询数据或读取模型摘要")
        return {"path": path, "content": file_path.read_text(encoding="utf-8")[:24_000]}

    def write_model(self, path: str, content: str) -> dict:
        file_path = self._path(path)
        models_dir = self.project_dir / "models"
        if not file_path.is_relative_to(models_dir) or file_path.suffix != ".sql":
            raise ValueError("只允许创建或修改 models/ 下的 .sql 文件")
        if len(content) > 60_000:
            raise ValueError("模型文件超过本项目的大小限制")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return {"written": path, "characters": len(content)}

    def query_sql(self, sql: str, limit: int = 50) -> dict:
        started = time.monotonic()
        with duckdb.connect(str(self.database_path), read_only=True, config={"enable_external_access": "false", "threads": 1}) as connection:
            if self.duckdb_timezone is not None:
                connection.execute("SET TimeZone = 'UTC'")
            statements = connection.extract_statements(sql)
            if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
                raise ValueError("探查工具只接受一条只读 SELECT/WITH 查询")
            cursor = connection.execute(sql)
            columns = [item[0] for item in cursor.description]
            rows = cursor.fetchmany(min(max(limit, 1), 100) + 1)
        cleaned_rows = [[str(value) if isinstance(value, float) and not math.isfinite(value) else value for value in row] for row in rows[:limit]]
        return {"columns": columns, "rows": json.loads(json.dumps(cleaned_rows, default=str)), "truncated": len(rows) > limit, "elapsed_seconds": round(time.monotonic() - started, 3)}

    def search_schema(self, query: str = "") -> dict:
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            if self.duckdb_timezone is not None:
                connection.execute("SET TimeZone = 'UTC'")
            rows = connection.execute("SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns WHERE table_schema NOT IN ('information_schema','pg_catalog') ORDER BY table_schema,table_name,ordinal_position").fetchall()
        words = [word.lower() for word in query.split()]
        tables: dict[str, list[dict]] = {}
        for schema, table, column, kind in rows:
            if words and not any(word in f"{schema} {table} {column}".lower() for word in words):
                continue
            tables.setdefault(f"{schema}.{table}", []).append({"name": column, "type": kind})
        selected = list(tables.items())[:60]
        return {"tables": dict(selected), "table_count": len(tables), "truncated": len(tables) > 60}

    def get_lineage(self, model: str = "") -> dict:
        nodes = []
        for path in sorted(self.project_dir.glob("models/**/*.sql")):
            content = path.read_text(encoding="utf-8")
            refs = re.findall(r"ref\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content)
            nodes.append({"model": path.stem, "path": str(path.relative_to(self.root)).replace("\\", "/"), "upstream": refs})
        if model:
            # Include both directions so a visible symptom can lead to its source.
            selected = {model}
            for _ in range(3):
                for node in nodes:
                    if node["model"] in selected or selected.intersection(node["upstream"]):
                        selected.add(node["model"])
                        selected.update(node["upstream"])
            nodes = [node for node in nodes if node["model"] in selected]
        return {"nodes": nodes[:100], "truncated": len(nodes) > 100, "source": "parsed dbt ref dependencies"}

    def run_dbt(self, command: str = "build", select: str | None = None, full_refresh: bool = False) -> dict:
        if command not in {"seed", "run", "test", "build", "compile"}:
            raise ValueError("不支持的 dbt 命令")
        if select is None and command != "seed":
            select = self.default_select
        argv = [sys.executable, "-m", "datapatch.dbt_runner", "--project", str(self.project_dir), command]
        if select:
            argv += ["--select", select]
        if full_refresh:
            argv += ["--full-refresh"]
        env = {**os.environ, "PYTHONUTF8": "1", "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
        env.pop("DEEPSEEK_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)
        started = time.monotonic()
        try:
            process = subprocess.run(argv, cwd=self.project_dir, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            result = {"success": process.returncode == 0, "returncode": process.returncode, "stdout": process.stdout[-16000:], "stderr": process.stderr[-3000:]}
        except subprocess.TimeoutExpired:
            result = {"success": False, "error": "dbt execution timeout (180 seconds)"}
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        artifact = self.project_dir / "target" / "run_results.json"
        if artifact.exists():
            data = json.loads(artifact.read_text(encoding="utf-8"))
            result["nodes"] = [{"id": x.get("unique_id"), "status": x.get("status"), "message": str(x.get("message", ""))[:1500]} for x in data.get("results", [])][-60:]
        return result

    def check_contracts(self) -> dict:
        results = []
        for path in sorted((self.root / "checks").glob("*.sql")):
            try:
                template = Environment(undefined=StrictUndefined).from_string(path.read_text(encoding="utf-8"))
                sql = template.render(ref=lambda name: '"main"."' + name.replace('"', '""') + '"', source=lambda schema, name: '"' + schema.replace('"', '""') + '"."' + name.replace('"', '""') + '"')
                data = self.query_sql(sql, limit=10)
                passed = not data["rows"]
                results.append({"name": path.stem, "passed": passed, "violations": data["rows"], "columns": data["columns"]})
            except Exception as exc:
                results.append({"name": path.stem, "passed": False, "error": str(exc)[:1200]})
        return {"passed": all(x["passed"] for x in results), "available": bool(results), "checks": results, "note": "Visible business contracts only. Empty means no additional contracts, not proof of data correctness. This does not expose the independent final evaluator."}

    def diff(self) -> str:
        current = {str(p.relative_to(self.root)).replace("\\", "/"): p.read_text(encoding="utf-8") for p in self.project_dir.glob("models/**/*.sql")}
        output = []
        for name in sorted(self.original.keys() | current.keys()):
            before, after = self.original.get(name, ""), current.get(name, "")
            if before != after:
                output.extend(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=f"a/{name}", tofile=f"b/{name}"))
        return "".join(output)

    def call(self, name: str, arguments: dict) -> Any:
        functions = {"list_files": self.list_files, "read_file": self.read_file, "write_model": self.write_model, "query_sql": self.query_sql, "run_dbt": self.run_dbt, "search_schema": self.search_schema, "get_lineage": self.get_lineage, "check_contracts": self.check_contracts}
        if name not in functions:
            raise ValueError(f"未知工具: {name}")
        return functions[name](**arguments)


def tool_definitions(domain_tools: bool = True, validation_tools: bool = True) -> list[dict]:
    specs = [
        ("list_files", "List project source files (excludes build artifacts).", {"directory": {"type": "string"}}, []),
        ("read_file", "Read a project SQL, YAML, Markdown or small CSV file.", {"path": {"type": "string"}}, ["path"]),
        ("write_model", "Replace the complete contents of a SQL model under models/.", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
        ("query_sql", "Run one read-only SELECT/WITH query against the live warehouse.", {"sql": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["sql"]),
        ("run_dbt", "Execute dbt and get structured failures. Use build to materialize changes before checking output.", {"command": {"type": "string", "enum": ["seed", "run", "test", "build", "compile"]}, "select": {"type": "string"}, "full_refresh": {"type": "boolean"}}, []),
    ]
    if domain_tools:
        specs += [
            ("search_schema", "Search live table/column/type metadata; empty query returns an overview.", {"query": {"type": "string"}}, []),
            ("get_lineage", "Get dbt model paths and upstream/downstream ref dependencies.", {"model": {"type": "string"}}, []),
        ]
    if validation_tools:
        specs += [("check_contracts", "Execute visible invariant SQL checks; returns counterexamples. Separate final tests are NOT accessible.", {}, [])]
    return [{"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": props, "required": required, "additionalProperties": False}}} for name, description, props, required in specs]
