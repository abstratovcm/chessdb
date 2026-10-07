import argparse
from pathlib import Path


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("serve", help="serve the read-only FastAPI backend")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--web-dist",
        type=Path,
        default=None,
        help="serve the built web/dist directory at / alongside the API",
    )
    parser.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> None:
    try:
        import uvicorn

        import chessdb.api.app as app_module
    except ImportError as exc:
        raise SystemExit(
            "fastapi/uvicorn not installed — pip install 'chessdb[site]' "
            "(or: uv sync --extra site)"
        ) from exc

    app = app_module.create_app(args.db, web_dist=args.web_dist)
    # Single worker: the DuckDB connection in app.state cannot span processes.
    uvicorn.run(app, host=args.host, port=args.port)
