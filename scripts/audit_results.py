"""Audit saved evaluation JSON without model calls or changes to source reports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from datapatch.audit import audit_reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="*", help="Report files or directories; defaults to artifacts/evaluations")
    parser.add_argument("--include-unamended", action="store_true", help="Also audit preserved unamended historical reports")
    parser.add_argument("--output", type=Path, help="Write audit JSON here; input reports are never changed")
    args = parser.parse_args()
    roots = args.paths or [Path(__file__).resolve().parents[1] / "artifacts/evaluations"]
    paths = [item for root in roots for item in (sorted(root.glob("*.json")) if root.is_dir() else [root])]
    audit = audit_reports(paths, include_unamended=args.include_unamended)
    payload = {"audit": audit}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=True, allow_nan=False))
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
