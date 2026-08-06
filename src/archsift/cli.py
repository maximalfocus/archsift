"""Command-line entry point for ArchSift."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn, TextIO

from archsift import package_version
from archsift.diagnostics import Diagnostic, ExitCode
from archsift.validation import ValidationResult, validate_workspace
from archsift.workspace import InitResult, initialize_workspace


def _output_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--json", action="store_true", dest="json_output", help="write JSON to stdout"
    )
    group.add_argument("--quiet", action="store_true", help="suppress command output")


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
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="create a versioned case workspace")
    init_parser.add_argument("case", type=Path, help="workspace directory to create")
    _output_options(init_parser)

    validate_parser = subparsers.add_parser("validate", help="validate a case workspace")
    validate_parser.add_argument("case", type=Path, help="workspace directory containing case.yaml")
    _output_options(validate_parser)
    return parser


def _json_payload(
    status: str,
    exit_code: ExitCode,
    diagnostics: tuple[Diagnostic, ...],
    **details: object,
) -> str:
    payload: dict[str, object] = {
        "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        "exit_code": int(exit_code),
        "status": status,
        **details,
    }
    # ensure_ascii=True keeps the payload ASCII-only by construction: only
    # JSON-standard \uXXXX escapes appear, parseable on any stream encoding.
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _print(text: str, *, stream: TextIO) -> None:
    """Print text without crashing when the stream cannot encode it."""
    try:
        print(text, file=stream)
    except UnicodeEncodeError:
        # Backslash-escapes keep the output encodable (and valid JSON) on
        # ASCII-only streams such as legacy Windows code pages.
        encoding = getattr(stream, "encoding", None) or "utf-8"
        escaped = text.encode(encoding, "backslashreplace").decode(encoding)
        print(escaped, file=stream)


def _emit(
    *,
    status: str,
    exit_code: ExitCode,
    diagnostics: tuple[Diagnostic, ...],
    json_output: bool,
    quiet: bool,
    success_message: str,
    details: dict[str, object],
) -> None:
    if quiet:
        return
    if json_output:
        _print(_json_payload(status, exit_code, diagnostics, **details), stream=sys.stdout)
        return
    if diagnostics:
        for diagnostic in diagnostics:
            _print(diagnostic.render(), stream=sys.stderr)
    else:
        _print(success_message, stream=sys.stdout)


def _internal_error(error: Exception, *, json_output: bool, quiet: bool) -> int:
    diagnostic = Diagnostic(
        id="internal-error",
        message="ArchSift could not complete the command because of an internal error.",
        file="<internal>",
        field="$",
        requirement="FR-012",
        remediation="Retry with the same inputs and report the failure if it persists.",
    )
    _emit(
        status="internal-error",
        exit_code=ExitCode.INTERNAL_ERROR,
        diagnostics=(diagnostic,),
        json_output=json_output,
        quiet=quiet,
        success_message="",
        details={"error_type": type(error).__name__},
    )
    return int(ExitCode.INTERNAL_ERROR)


def _run_init(path: Path, *, json_output: bool, quiet: bool) -> int:
    try:
        result: InitResult = initialize_workspace(path)
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)
    status = "created" if result.exit_code == ExitCode.SUCCESS else "invalid"
    _emit(
        status=status,
        exit_code=result.exit_code,
        diagnostics=result.diagnostics,
        json_output=json_output,
        quiet=quiet,
        success_message=f"Created ArchSift case workspace: {path}",
        details={"workspace": str(path)},
    )
    return int(result.exit_code)


def _run_validate(path: Path, *, json_output: bool, quiet: bool) -> int:
    try:
        result: ValidationResult = validate_workspace(path)
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)
    status = "valid" if result.exit_code == ExitCode.SUCCESS else "invalid"
    details: dict[str, object] = {"file": "case.yaml"}
    if result.dossier is not None:
        details["schema_version"] = result.dossier.schema_version
    _emit(
        status=status,
        exit_code=result.exit_code,
        diagnostics=result.diagnostics,
        json_output=json_output,
        quiet=quiet,
        success_message="Valid ArchSift dossier: case.yaml (schema 1)",
        details=details,
    )
    return int(result.exit_code)


def _usage_error(parser: argparse.ArgumentParser, message: str) -> NoReturn:
    parser.error(message)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ArchSift CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        if args.command is not None:
            _usage_error(parser, "--version cannot be combined with a command")
        print(package_version())
        return int(ExitCode.SUCCESS)
    if args.command == "init":
        return _run_init(args.case, json_output=args.json_output, quiet=args.quiet)
    if args.command == "validate":
        return _run_validate(args.case, json_output=args.json_output, quiet=args.quiet)
    parser.print_help()
    return int(ExitCode.SUCCESS)
