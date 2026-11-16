"""HTTP workbench contract tests; no model access or background jobs required."""

from fastapi.testclient import TestClient

from datapatch.web import create_app


class FakeRunService:
    def __init__(self):
        self.started = []

    def tasks(self):
        return [{"id": "join-fanout", "title": "修复重复关联"}]

    def task_detail(self, task_id):
        if task_id != "join-fanout":
            raise KeyError("任务不存在")
        return {"id": task_id, "title": "修复重复关联", "description": "销售额出现重复累计"}

    def config_status(self):
        return {"api_key_configured": False, "model": "deepseek-chat", "container_available": False}

    def list_runs(self):
        return [self.get_run("r-1")]

    def get_run(self, run_id):
        if run_id != "r-1":
            raise FileNotFoundError("运行不存在")
        return {"run_id": run_id, "task_id": "join-fanout", "status": "completed", "verification": {"passed": False, "checks": [{"name": "sales", "passed": False, "expected": 100, "actual": 200}]}, "diff": "+ SELECT total", "events": []}

    def start_run(self, **kwargs):
        if kwargs["mode"] == "invalid":
            raise ValueError("不支持的执行方案")
        self.started.append(kwargs)
        return {"run_id": "r-2", "status": "queued"}

    def reports(self):
        return [{"name": "evaluation.json", "title": "模式对比"}]

    def read_report(self, name):
        if name != "evaluation.json":
            raise FileNotFoundError("评测报告不存在")
        return {"by_mode": {"verified": {"count": 3, "pass_rate": 1.0}}}


def test_static_workbench_and_config_are_available_without_model():
    client = TestClient(create_app(FakeRunService()))
    response = client.get("/")
    assert response.status_code == 200
    assert "数据工程修复工作台" in response.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/api/config").json()["api_key_configured"] is False


def test_read_routes_keep_verification_separate_from_run_completion():
    client = TestClient(create_app(FakeRunService()))
    assert client.get("/api/tasks").json()[0]["id"] == "join-fanout"
    assert client.get("/api/tasks/join-fanout").json()["description"]
    assert client.get("/api/runs").json()[0]["run_id"] == "r-1"
    run = client.get("/api/runs/r-1").json()
    assert run["status"] == "completed"
    assert run["verification"]["passed"] is False
    assert client.get("/api/reports").json()[0]["name"] == "evaluation.json"
    assert client.get("/api/reports/evaluation.json").json()["by_mode"]["verified"]["count"] == 3


def test_start_route_passes_budget_and_provider_to_service():
    service = FakeRunService()
    client = TestClient(create_app(service))
    response = client.post("/api/runs", json={"task_id": "join-fanout", "mode": "context", "provider": "deepseek", "max_steps": 8})
    assert response.status_code == 202
    assert response.json() == {"run_id": "r-2", "status": "queued"}
    assert service.started == [{"task_id": "join-fanout", "mode": "context", "provider": "deepseek", "max_steps": 8}]


def test_missing_records_and_invalid_requests_have_clear_http_errors():
    client = TestClient(create_app(FakeRunService()))
    assert client.get("/api/tasks/missing").status_code == 404
    assert client.get("/api/runs/missing").status_code == 404
    assert client.get("/api/reports/missing.json").status_code == 404
    response = client.post("/api/runs", json={"task_id": "join-fanout", "mode": "invalid"})
    assert response.status_code == 400
    assert response.json()["detail"] == "不支持的执行方案"
    assert client.post("/api/runs", json={"task_id": "join-fanout", "max_steps": 0}).status_code == 422
    assert client.post("/api/runs", json={"task_id": "join-fanout", "max_steps": 41}).status_code == 422
