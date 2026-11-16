"""Freeze evaluated code and a file-hash manifest without credentials or data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from datapatch.config import ROOT


def freeze(destination: Path) -> dict:
    files = {}
    for directory in ("src", "integrations", "scripts", "tests", "tasks", "docs"):
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and path.suffix in {".py", ".md", ".html", ".css", ".js"} and "__pycache__" not in path.parts:
                files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for name in ("README.md", "pyproject.toml", "requirements.lock", ".env.example", "Dockerfile", "compose.yaml", "LICENSE"):
        if (ROOT / name).is_file():
            files[name] = (ROOT / name).read_bytes()
    # Reviewed delivery patches are source artifacts, kept outside every
    # isolated solver workspace. Recorded trajectories remain separate.
    for directory in ("public_fixes", "public_contracts"):
        for path in (ROOT / "examples" / directory).rglob("*"):
            if path.is_file() and path.suffix in {".sql", ".json", ".md"}:
                files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for path in (ROOT / "LICENSES").rglob("*"):
        if path.is_file():
            files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    core = hashlib.sha256()
    for name in sorted(n for n in files if n.startswith("src/datapatch/") and len(Path(n).parts) == 3 and n.endswith(".py")):
        core.update(Path(name).name.encode())
        core.update(files[name])
    manifest = {"core_source_sha256": core.hexdigest(), "files": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("Snapshot already exists; use a new version name")
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
        archive.writestr("source-manifest.json", json.dumps(manifest, indent=2))
    return {"path": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "core_source_sha256": manifest["core_source_sha256"], "files": len(files)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    print(json.dumps(freeze(parser.parse_args().destination), indent=2))
