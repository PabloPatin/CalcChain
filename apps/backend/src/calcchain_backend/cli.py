from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from calcchain_backend.app import create_app
from calcchain_backend.settings import create_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="calcchain-backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run CalcChain backend API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8765, type=int)
    serve.add_argument("--project-root", default=".", help="CalcChain repository/workspace root")
    serve.add_argument("--lan", action="store_true", help="Bind to 0.0.0.0 and mark server mode as LAN")
    serve.add_argument("--reload", action="store_true", help="Enable uvicorn reload")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "serve":
        host = "0.0.0.0" if args.lan else args.host
        settings = create_settings(Path(args.project_root), mode="lan" if args.lan else "local")
        app = create_app(settings)
        uvicorn.run(app, host=host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
