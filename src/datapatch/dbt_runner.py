"""Run dbt in a child process so each invocation has fresh adapter state."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("command", choices=["seed", "run", "test", "build", "compile"])
    parser.add_argument("--select")
    parser.add_argument("--full-refresh", action="store_true")
    args = parser.parse_args()
    from dbt.cli.main import dbtRunner

    os.environ["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
    command = [args.command, "--project-dir", str(args.project), "--profiles-dir", str(args.project), "--no-use-colors", "--quiet"]
    if args.select:
        command += ["--select", args.select]
    if args.full_refresh:
        command += ["--full-refresh"]
    result = dbtRunner().invoke(command)
    print(json.dumps({"success": bool(result.success), "exception": str(result.exception) if result.exception else None}, ensure_ascii=False))
    raise SystemExit(0 if result.success else 1)


if __name__ == "__main__":
    main()

