"""CLI for synthetic support-pack build, install, and local activation."""

import argparse
import json
from pathlib import Path

from .core import active, activate, build, install, read_json, verify_bundle, write_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a2z-resolution-network")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("build", help="validate and bundle a synthetic pack")
    p.add_argument("pack_dir", type=Path)
    p.add_argument("--engine-source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("verify", help="replay and verify a bundle")
    p.add_argument("bundle", type=Path)
    p = commands.add_parser("install", help="install a verified immutable bundle")
    p.add_argument("bundle", type=Path)
    p.add_argument("--registry", type=Path, required=True)
    p = commands.add_parser("activate", help="select an installed bundle for one customer scope")
    p.add_argument("--registry", type=Path, required=True)
    p.add_argument("--customer", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--sha256", required=True)
    p = commands.add_parser("active", help="verify and print selected knowledge path")
    p.add_argument("--registry", type=Path, required=True)
    p.add_argument("--customer", required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        result = write_bundle(build(args.pack_dir, args.engine_source), args.output)
    elif args.command == "verify":
        result = verify_bundle(read_json(args.bundle))
    elif args.command == "install":
        result = install(args.bundle, args.registry)
    elif args.command == "activate":
        result = activate(args.registry, args.customer, args.id, args.version, args.sha256)
    else:
        result = active(args.registry, args.customer)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
