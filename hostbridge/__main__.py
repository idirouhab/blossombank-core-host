import argparse
import json
import logging
import os
from pathlib import Path

from .application import Application
from .errors import DomainError
from .httpserver import RegionServer


def parser():
    root = argparse.ArgumentParser(description="BlossomBank host region and batch controller")
    root.add_argument("--database", type=Path, help="override host database path")
    actions = root.add_subparsers(dest="command", required=True)
    server = actions.add_parser("serve", help="start online compatibility region")
    server.add_argument("--bind", default=os.environ.get("BIND", os.environ.get("HOST", "127.0.0.1")))
    server.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8082")))
    actions.add_parser("init")
    actions.add_parser("reconcile")
    actions.add_parser("expire-holds")
    actions.add_parser("batch-runs")
    for command in ("close-day", "open-day", "accrue", "settle"):
        action = actions.add_parser(command)
        action.add_argument("date")
    clearing = actions.add_parser("import-clearing")
    clearing.add_argument("path", type=Path)
    recover = actions.add_parser("recover-batch")
    recover.add_argument("run_id")
    backup = actions.add_parser("backup")
    backup.add_argument("destination", type=Path)
    unload = actions.add_parser("unload-accounts")
    unload.add_argument("destination", type=Path)
    spool = actions.add_parser("statement-legacy")
    spool.add_argument("account")
    spool.add_argument("start")
    spool.add_argument("end")
    return root


def main():
    args = parser().parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = Application(args.database)
    actions = {"init": app.health, "reconcile": app.reconciliation.run,
               "expire-holds": app.holds.expire, "batch-runs": app.clearing.list_runs}
    if args.command == "serve":
        with RegionServer((args.bind, args.port), app) as server:
            logging.info("BLSONL1 online on %s:%s", *server.server_address)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                logging.info("region stopped")
        return 0
    if args.command in actions:
        result = actions[args.command]()
    elif args.command == "close-day":
        result = app.daybook.close(args.date)
    elif args.command == "open-day":
        result = app.daybook.open(args.date)
    elif args.command == "accrue":
        result = app.interest.accrue(args.date)
    elif args.command == "settle":
        result = app.interest.settle(args.date)
    elif args.command == "import-clearing":
        result = app.clearing.import_file(args.path)
    elif args.command == "recover-batch":
        result = app.clearing.recover(args.run_id)
    elif args.command == "backup":
        result = {"backup": app.database.backup(args.destination)}
    elif args.command == "unload-accounts":
        result = app.unload.export(args.destination)
    elif args.command == "statement-legacy":
        print(app.statements.print_spool(args.account, args.start, args.end), end="")
        return 0
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, indent=2))
    return 2 if result.get("status") == "BREAKS" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DomainError as exc:
        print(json.dumps(exc.response()))
        raise SystemExit(1) from None
