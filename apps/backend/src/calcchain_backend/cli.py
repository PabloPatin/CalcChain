from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from calcchain_backend.app import create_app
from calcchain_backend.control import request_new_pairing_code
from calcchain_backend.settings import create_settings


BACKEND_SRC_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="calcchain-backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run CalcChain backend API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8765, type=int)
    serve.add_argument("--project-root", default=".", help="CalcChain repository/workspace root")
    serve.add_argument("--lan", action="store_true", help="Bind to 0.0.0.0 and mark server mode as LAN")
    serve.add_argument("--reload", action="store_true", help="Enable uvicorn reload")

    subparsers.add_parser("pair", help="Generate a one-time LAN pairing code")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "serve":
        host = "0.0.0.0" if args.lan else args.host
        settings = create_settings(Path(args.project_root), mode="lan" if args.lan else "local", host=host, port=args.port)
        if args.lan:
            print("CalcChain LAN auth is enabled.")
            print("Run `calcchain-backend pair` in this user account to generate an 8-digit pairing code.")
        if args.reload:
            reload_dirs = _reload_dirs(settings.project_root)
            os.environ["CALCCHAIN_BACKEND_PROJECT_ROOT"] = str(settings.project_root)
            os.environ["CALCCHAIN_BACKEND_MODE"] = settings.mode
            os.environ["CALCCHAIN_BACKEND_HOST"] = settings.host
            os.environ["CALCCHAIN_BACKEND_PORT"] = str(settings.port)
            uvicorn.run(
                "calcchain_backend.app:create_app_from_env",
                host=host,
                port=args.port,
                reload=True,
                reload_dirs=reload_dirs,
                factory=True,
            )
            return

        app = create_app(settings)
        uvicorn.run(app, host=host, port=args.port)
    elif args.command == "pair":
        print(request_new_pairing_code())


def _reload_dirs(project_root: Path) -> list[str]:
    candidates = [
        BACKEND_SRC_DIR,
        project_root / "packages" / "core" / "src",
        project_root / "packages" / "plugin_system" / "src",
    ]
    return [str(path) for path in candidates if path.is_dir()]


if __name__ == "__main__":
    main()
