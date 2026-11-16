"""Local DataPatch workbench. API credentials stay in the server process."""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


STATIC_DIR = Path(__file__).with_name("static")


class RunRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=200)
    mode: str = Field(default="verified", min_length=1, max_length=40)
    provider: str = Field(default="deepseek", min_length=1, max_length=40)
    max_steps: int = Field(default=12, ge=1, le=40)


def create_app(service: Any = None) -> FastAPI:
    """Accept a service instance so the HTTP contract can be tested offline."""
    app = FastAPI(title="DataPatch", version="0.1.0")
    app.state.run_service = service
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def call(request: Request, method: str, *args: Any, **kwargs: Any) -> Any:
        if request.app.state.run_service is None:
            from datapatch.service import RunService

            request.app.state.run_service = RunService()
        try:
            return getattr(request.app.state.run_service, method)(*args, **kwargs)
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/config")
    def config(request: Request) -> Any:
        return call(request, "config_status")

    @app.get("/api/tasks")
    def tasks(request: Request) -> Any:
        return call(request, "tasks")

    @app.get("/api/tasks/{task_id}")
    def task(task_id: str, request: Request) -> Any:
        return call(request, "task_detail", task_id)

    @app.get("/api/runs")
    def runs(request: Request) -> Any:
        return call(request, "list_runs")

    @app.get("/api/runs/{run_id}")
    def run(run_id: str, request: Request) -> Any:
        return call(request, "get_run", run_id)

    @app.post("/api/runs", status_code=202)
    def start(body: RunRequest, request: Request) -> Any:
        return call(request, "start_run", **body.model_dump())

    @app.get("/api/reports")
    def reports(request: Request) -> Any:
        return call(request, "reports")

    @app.get("/api/reports/{name}")
    def report(name: str, request: Request) -> Any:
        return call(request, "read_report", name)

    return app


app = create_app()
