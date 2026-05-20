import argparse
import sys

import uvicorn

from calcchain_backend.app import create_app
from calcchain_backend.config import BackendConfig
from calcchain_backend.control import ControlServer, request_new_pairing_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="calcchain-backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run CalcChain backend")
    serve.add_argument("--lan", action="store_true", help="Listen on LAN and require browser pairing")
    serve.add_argument("--host", default=None, help="Override listen host")
    serve.add_argument("--port", type=int, default=8765, help="Listen port")
    serve.add_argument(
        "--allow-origin",
        action="append",
        default=None,
        help="Allowed browser origin. Can be passed multiple times.",
    )

    subparsers.add_parser(
        "pair",
        help="Generate a fresh one-time pairing code through the local control socket",
    )

    return parser


def serve(args: argparse.Namespace) -> None:
    host = args.host or ("0.0.0.0" if args.lan else "127.0.0.1")
    config = BackendConfig(
        host=host,
        port=args.port,
        lan=args.lan,
        auth_required=args.lan,
        allowed_origins=args.allow_origin or BackendConfig().allowed_origins,
    )
    app = create_app(config)

    control_server: ControlServer | None = None
    if config.auth_required:
        control_server = ControlServer(app.state.pairing)
        control_server.start()

        code = app.state.pairing.generate()
        print("=" * 72, flush=True)
        print("CalcChain LAN mode is enabled.", flush=True)
        print(f"Open the UI and enter this one-time pairing code: {code}", flush=True)
        print(f"The code expires in {config.pairing_ttl_seconds} seconds.", flush=True)
        print("To generate another code on this server, run: calcchain-backend pair", flush=True)
        print("Over SSH, run: ssh user@calc-server.local calcchain-backend pair", flush=True)
        print("Do not send this code through public or untrusted channels.", flush=True)
        print("=" * 72, flush=True)

    try:
        uvicorn.run(app, host=config.host, port=config.port)
    finally:
        if control_server is not None:
            control_server.close()


def pair() -> None:
    code = request_new_pairing_code()
    print(code, flush=True)


def main() -> None:
    args = build_parser().parse_args()

    try:
        if args.command == "serve":
            serve(args)
        elif args.command == "pair":
            pair()
        else:
            raise RuntimeError(f"Unknown command: {args.command}")
    except Exception as exc:  # noqa: BLE001 - CLI should display clean errors.
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
