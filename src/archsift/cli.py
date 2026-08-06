"""Command-line entry point for ArchSift."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from archsift import package_version


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser without performing I/O."""
    parser = argparse.ArgumentParser(
        prog="archsift",
        description="Evidence-calibrated architecture decision support.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the installed ArchSift version and exit",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the minimal ArchSift CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(package_version())
    else:
        parser.print_help()
    return 0
