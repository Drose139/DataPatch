from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="datapatch")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("tasks", help="List reproducible demo tasks")
    sub.add_parser("doctor", help="Check credentials and runtime without making an API request")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    run = sub.add_parser("run")
    run.add_argument("task_id")
    run.add_argument("--mode", choices=["baseline", "react", "context", "verified"], default="verified")
    run.add_argument("--max-steps", type=int, default=12)
    evaluation = sub.add_parser("eval")
    evaluation.add_argument("--modes", nargs="+", default=["verified"])
    evaluation.add_argument("--tasks", nargs="+")
    evaluation.add_argument("--repeats", type=int, default=1)
    evaluation.add_argument("--workers", type=int, default=1)
    evaluation.add_argument("--max-steps", type=int, default=12)
    evaluation.add_argument("--name")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        uvicorn.run("datapatch.web:app", host=args.host, port=args.port)
        return
    if args.command == "eval":
        from .evaluation import evaluate
        result = evaluate(args.modes, args.tasks, args.repeats, args.workers, args.max_steps, args.name)
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        return
    from .service import RunService
    service = RunService()
    if args.command == "tasks":
        result = service.tasks()
    elif args.command == "doctor":
        result = service.config_status()
    else:
        result = service.run_sync(args.task_id, args.mode, args.max_steps)
        result = {key: value for key, value in result.items() if key != "events"}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
