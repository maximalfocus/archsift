"""Command-line entry point for ArchSift."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn, TextIO

from archsift import package_version
from archsift.artefacts import (
    EvidenceArtefactError,
    EvidenceArtefactFailure,
    evidence_artefact_identities,
)
from archsift.comparison import (
    ComparisonInputError,
    canonical_comparison_bytes,
    compare_decision_records,
    load_decision_record,
    render_human_comparison,
)
from archsift.decision_record import canonical_decision_record_bytes, compose_decision_record
from archsift.diagnostics import Diagnostic, ExitCode
from archsift.markdown_report import render_markdown_decision_report
from archsift.method import METHOD_SPECIFICATION, METHOD_VERSION, method_metadata
from archsift.persistence import (
    RecordPersistenceError,
    RecordPersistenceFailure,
    persist_decision_outputs,
)
from archsift.rules import (
    RULESET_VERSION,
    evaluate_assessment_prerequisites,
    list_rules,
)
from archsift.usability import validate_usability_results
from archsift.validation import (
    ValidationResult,
    evaluate_agency_necessity_readiness,
    evaluate_autonomy_permission_readiness,
    evaluate_candidate_comparison_readiness,
    evaluate_consistency_readiness,
    evaluate_problem_value_readiness,
    validate_workspace,
)
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

    rules_parser = subparsers.add_parser("rules", help="list packaged decision rules")
    _output_options(rules_parser)

    assess_parser = subparsers.add_parser(
        "assess", help="produce immutable JSON and Markdown decision records"
    )
    assess_parser.add_argument("case", type=Path, help="workspace directory containing case.yaml")
    assess_parser.add_argument(
        "--external-evidence-root",
        type=Path,
        help="explicitly authorise one external evidence directory",
    )
    _output_options(assess_parser)

    compare_parser = subparsers.add_parser(
        "compare", help="compare two immutable canonical decision records"
    )
    compare_parser.add_argument("old", type=Path, help="earlier canonical decision-record JSON")
    compare_parser.add_argument("new", type=Path, help="later canonical decision-record JSON")
    _output_options(compare_parser)

    usability_parser = subparsers.add_parser(
        "usability-results", help="validate one independent usability result cohort"
    )
    usability_parser.add_argument("results", type=Path, help="completed usability-results JSON")
    _output_options(usability_parser)
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
        details["action_count"] = (
            len(result.dossier.task.actions) if result.dossier.task is not None else 0
        )
        details["evidence_count"] = len(result.dossier.evidence)
        problem_value = result.dossier.problem_value
        readiness = evaluate_problem_value_readiness(result.dossier)
        details["problem_value_defined"] = problem_value is not None
        details["outcome_count"] = len(problem_value.outcomes) if problem_value is not None else 0
        details["constraint_count"] = (
            len(problem_value.constraints) if problem_value is not None else 0
        )
        details["problem_value_ready"] = readiness.ready
        agency_necessity = result.dossier.agency_necessity
        agency_readiness = evaluate_agency_necessity_readiness(result.dossier)
        details["agency_necessity_defined"] = agency_necessity is not None
        details["agency_necessity_ready"] = agency_readiness.ready
        details["residual_case_count"] = (
            len(agency_necessity.residual_cases) if agency_necessity is not None else 0
        )
        autonomy_permission = result.dossier.autonomy_permission
        autonomy_readiness = evaluate_autonomy_permission_readiness(result.dossier)
        details["autonomy_permission_defined"] = autonomy_permission is not None
        details["autonomy_permission_ready"] = autonomy_readiness.ready
        details["hard_veto_count"] = (
            len(autonomy_permission.hard_vetoes) if autonomy_permission is not None else 0
        )
        details["mandatory_human_control_count"] = (
            len(autonomy_permission.mandatory_human_controls)
            if autonomy_permission is not None
            else 0
        )
        candidate_comparison = result.dossier.candidate_comparison
        candidate_readiness = evaluate_candidate_comparison_readiness(result.dossier)
        details["candidate_comparison_defined"] = candidate_comparison is not None
        details["candidate_comparison_ready"] = candidate_readiness.ready
        details["candidate_count"] = (
            len(candidate_comparison.candidates) if candidate_comparison is not None else 0
        )
        details["comparison_count"] = (
            len(candidate_comparison.comparisons) if candidate_comparison is not None else 0
        )
        consistency_readiness = evaluate_consistency_readiness(result.dossier)
        details["consistency_ready"] = consistency_readiness.ready
        prerequisites = evaluate_assessment_prerequisites(result.dossier)
        details["assessment_prerequisites_ready"] = prerequisites.ready
        details["prerequisite_finding_count"] = len(prerequisites.findings)
        details["ruleset_version"] = prerequisites.ruleset_version
        details["schema_version"] = result.dossier.schema_version
        details["task_defined"] = result.dossier.task is not None
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


_ARTEFACT_UNAVAILABLE_FAILURES = {
    EvidenceArtefactFailure.EXTERNAL_ROOT_REQUIRED,
    EvidenceArtefactFailure.TARGET_MISSING,
    EvidenceArtefactFailure.TARGET_UNREADABLE,
}
_PERSISTENCE_UNSAFE_FAILURES = {
    RecordPersistenceFailure.WORKSPACE_UNAVAILABLE,
    RecordPersistenceFailure.OUTPUT_ROOT_UNSAFE,
    RecordPersistenceFailure.TARGET_UNSAFE,
}


def _emit_assess_failure(
    error: EvidenceArtefactError | RecordPersistenceError,
    *,
    json_output: bool,
    quiet: bool,
) -> int:
    if isinstance(error, EvidenceArtefactError):
        exit_code = (
            ExitCode.ARTEFACT_UNAVAILABLE
            if error.category in _ARTEFACT_UNAVAILABLE_FAILURES
            else ExitCode.UNSAFE_PATH
        )
        diagnostic_id = f"evidence-artefact-{error.category.value}"
        diagnostic_file = "case.yaml"
        status = "artefact-unavailable" if exit_code is ExitCode.ARTEFACT_UNAVAILABLE else "unsafe"
    else:
        exit_code = (
            ExitCode.UNSAFE_PATH
            if error.category in _PERSISTENCE_UNSAFE_FAILURES
            else ExitCode.PERSISTENCE_FAILED
        )
        diagnostic_id = f"decision-record-{error.category.value}"
        diagnostic_file = "output"
        status = "unsafe" if exit_code is ExitCode.UNSAFE_PATH else "persistence-failed"
    diagnostic = Diagnostic(
        id=diagnostic_id,
        message=error.message,
        file=diagnostic_file,
        field=error.field,
        requirement=error.requirement,
        remediation=error.remediation,
    )
    _emit(
        status=status,
        exit_code=exit_code,
        diagnostics=(diagnostic,),
        json_output=json_output,
        quiet=quiet,
        success_message="",
        details={},
    )
    return int(exit_code)


def _write_canonical_stdout(content: bytes) -> None:
    stream = sys.stdout
    binary = getattr(stream, "buffer", None)
    if binary is not None:
        binary.write(content)
        binary.flush()
    else:
        stream.write(content.decode("ascii"))
        stream.flush()


def _run_assess(
    path: Path,
    *,
    external_evidence_root: Path | None,
    json_output: bool,
    quiet: bool,
) -> int:
    try:
        result = validate_workspace(path)
        if result.exit_code is not ExitCode.SUCCESS or result.dossier is None:
            _emit(
                status="invalid",
                exit_code=result.exit_code,
                diagnostics=result.diagnostics,
                json_output=json_output,
                quiet=quiet,
                success_message="",
                details={"file": "case.yaml"},
            )
            return int(result.exit_code)
        artefacts = evidence_artefact_identities(
            result.dossier,
            workspace=path,
            external_root=external_evidence_root,
        )
        record = compose_decision_record(
            result.dossier,
            tool_version=package_version(),
            artefact_identities=artefacts,
        )
        content = canonical_decision_record_bytes(record)
        report = render_markdown_decision_report(record)
        persisted = persist_decision_outputs(path, record, content, report)
    except (EvidenceArtefactError, RecordPersistenceError) as error:
        return _emit_assess_failure(error, json_output=json_output, quiet=quiet)
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)

    if quiet:
        return int(ExitCode.SUCCESS)
    if json_output:
        _write_canonical_stdout(content)
        return int(ExitCode.SUCCESS)
    _print(
        f"Assessment {record.assessment.verdict.value}: {record.record_content_identity} "
        f"-> {persisted.json.relative_path}; report -> {persisted.markdown.relative_path}",
        stream=sys.stdout,
    )
    return int(ExitCode.SUCCESS)


def _emit_compare_failure(
    error: ComparisonInputError,
    *,
    json_output: bool,
    quiet: bool,
) -> int:
    exit_code = error.exit_code
    status = {
        ExitCode.ARTEFACT_UNAVAILABLE: "artefact-unavailable",
        ExitCode.MALFORMED_INPUT: "malformed",
        ExitCode.UNSAFE_PATH: "unsafe",
        ExitCode.UNSUPPORTED_SCHEMA: "unsupported",
    }[exit_code]
    diagnostic = Diagnostic(
        id=f"compare-{error.category.value}",
        message=error.message,
        file=f"{error.role}-record",
        field=error.field,
        requirement="FR-013",
        remediation=error.remediation,
    )
    _emit(
        status=status,
        exit_code=exit_code,
        diagnostics=(diagnostic,),
        json_output=json_output,
        quiet=quiet,
        success_message="",
        details={},
    )
    return int(exit_code)


def _run_compare(
    old_path: Path,
    new_path: Path,
    *,
    json_output: bool,
    quiet: bool,
) -> int:
    try:
        root = Path(".")
        old = load_decision_record(old_path, root=root, role="old")
        new = load_decision_record(new_path, root=root, role="new")
        comparison = compare_decision_records(old, new)
    except ComparisonInputError as error:
        return _emit_compare_failure(error, json_output=json_output, quiet=quiet)
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)

    if quiet:
        return int(ExitCode.SUCCESS)
    if json_output:
        _write_canonical_stdout(canonical_comparison_bytes(comparison))
        return int(ExitCode.SUCCESS)
    _print(render_human_comparison(comparison), stream=sys.stdout)
    return int(ExitCode.SUCCESS)


def _run_usability_results(path: Path, *, json_output: bool, quiet: bool) -> int:
    try:
        result = validate_usability_results(path)
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)
    status = "criterion-met" if result.exit_code is ExitCode.SUCCESS else "invalid"
    if any(item.id == "usability-threshold-not-met" for item in result.diagnostics):
        status = "criterion-not-met"
    _emit(
        status=status,
        exit_code=result.exit_code,
        diagnostics=result.diagnostics,
        json_output=json_output,
        quiet=quiet,
        success_message=(
            f"Usability criterion met: {result.passed_session_count} of "
            f"{result.session_count} sessions passed (protocol {result.protocol_version})"
        ),
        details={
            "criterion_met": result.criterion_met,
            "passed_session_count": result.passed_session_count,
            "protocol_version": result.protocol_version,
            "session_count": result.session_count,
        },
    )
    return int(result.exit_code)


def _run_rules(*, json_output: bool, quiet: bool) -> int:
    rules = list_rules()
    if quiet:
        return int(ExitCode.SUCCESS)
    if json_output:
        _print(
            _json_payload(
                "ok",
                ExitCode.SUCCESS,
                (),
                method=method_metadata(),
                rules=[rule.to_dict() for rule in rules],
                ruleset_version=RULESET_VERSION,
            ),
            stream=sys.stdout,
        )
        return int(ExitCode.SUCCESS)
    _print(
        f"ArchSift ruleset {RULESET_VERSION} (method {METHOD_VERSION}; {METHOD_SPECIFICATION})",
        stream=sys.stdout,
    )
    for rule in rules:
        _print(
            f"{rule.id} [{rule.effect.value}; {rule.requirement}] {rule.description} "
            f"Consequence: {rule.consequence} Rationale: {rule.source_rationale} "
            f"Method: {rule.rationale_id} Sources: {','.join(rule.source_ids)}",
            stream=sys.stdout,
        )
    return int(ExitCode.SUCCESS)


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
    if args.command == "rules":
        return _run_rules(json_output=args.json_output, quiet=args.quiet)
    if args.command == "assess":
        return _run_assess(
            args.case,
            external_evidence_root=args.external_evidence_root,
            json_output=args.json_output,
            quiet=args.quiet,
        )
    if args.command == "compare":
        return _run_compare(
            args.old,
            args.new,
            json_output=args.json_output,
            quiet=args.quiet,
        )
    if args.command == "usability-results":
        return _run_usability_results(
            args.results,
            json_output=args.json_output,
            quiet=args.quiet,
        )
    parser.print_help()
    return int(ExitCode.SUCCESS)
