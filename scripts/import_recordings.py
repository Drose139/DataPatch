"""Import shipped actual recordings without making an API call."""
from __future__ import annotations

import json
from pathlib import Path

from datapatch.config import ROOT, Settings
from datapatch.service import write_json


def main():
    settings = Settings.load()
    imported = 0
    for source in sorted((ROOT / "examples/recorded_runs").glob("*.json")):
        record = json.loads(source.read_text(encoding="utf-8"))
        target = settings.artifacts_dir / "runs" / record["run_id"] / "run.json"
        if target.exists():
            continue
        write_json(target, record)
        imported += 1
    for source in sorted((ROOT / "results").glob("*.json")):
        data = json.loads(source.read_text(encoding="utf-8"))
        if "dataset" not in data or "records" not in data:
            continue
        target = settings.artifacts_dir / "evaluations" / source.name
        if not target.exists():
            write_json(target, data)
    # Keep source archives beside exported reports so offline audits can bind
    # historical hashes without relying on the original machine's paths.
    import shutil
    for source in (ROOT / "results").glob("*_source.zip"):
        target = settings.artifacts_dir / "evaluations" / source.name
        if not target.exists():
            shutil.copy2(source, target)
    print(f"Imported {imported} actual recorded runs. No model calls were made.")


if __name__ == "__main__":
    main()
