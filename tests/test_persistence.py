import json
from pathlib import Path

from datapatch.service import write_json


def test_transient_windows_replace_error_does_not_lose_run(monkeypatch, tmp_path):
    original = Path.replace
    attempts = []

    def briefly_locked(path, target):
        attempts.append(str(path))
        if len(attempts) == 1:
            raise PermissionError("simulated Windows sharing violation")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", briefly_locked)
    monkeypatch.setattr("datapatch.service.time.sleep", lambda seconds: None)
    path = tmp_path / "run.json"
    write_json(path, {"run_id": "actual-test", "status": "completed"})
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "completed"
    assert len(attempts) == 2
