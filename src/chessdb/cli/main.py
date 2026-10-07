import argparse

from chessdb.cli import eval as eval_cmd
from chessdb.cli import (
    export,
    fetch_engine,
    generate,
    import_epd,
    init,
    merge,
    metrics,
    serve,
)
from chessdb.cli import run as run_cmd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chessdb")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init.register(subparsers)
    fetch_engine.register(subparsers)
    eval_cmd.register(subparsers)
    generate.register(subparsers)
    import_epd.register(subparsers)
    run_cmd.register(subparsers)
    merge.register(subparsers)
    metrics.register(subparsers)
    export.register(subparsers)
    serve.register(subparsers)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
