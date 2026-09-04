"""Command-line entry point for ArchSift."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn, TextIO, cast

from archsift import package_version
from archsift.artefacts import (
    EvidenceArtefactError,
    EvidenceArtefactFailure,
    evidence_artefact_identities,
)
from archsift.authoring import dossier_schema_surface, prerequisite_worklist
from archsift.authoring_results import validate_authoring_results
from archsift.canonical import JsonObject, canonical_json_bytes
from archsift.case_view import CaseViewError, construct_case_view, load_case_view_request
from archsift.comparison import (
    ComparisonInputError,
    canonical_comparison_bytes,
    compare_decision_records,
    load_decision_record,
    render_human_comparison,
    resolve_record_path,
)
from archsift.corpus import packaged_corpus_bytes, packaged_corpus_snapshot
from archsift.decision import ArchitectureVerdict, evaluate_assessment
from archsift.decision_record import DecisionRecordError, compose_decision_record
from archsift.diagnostics import Diagnostic, ExitCode
from archsift.evidence_set import (
    evidence_set_profile,
    profile_bytes,
    profile_lines,
    validate_slot_coverage,
)
from archsift.framework import build_framework_card, card_lines
from archsift.graph_change import (
    GraphChangeError,
    load_graph_change_proposal,
    validate_graph_change,
)
from archsift.html_report import render_detailed_html_report, render_executive_html_report
from archsift.knowledge_graph import (
    NodeKind,
    RelationKind,
    SnapshotError,
    SnapshotFileError,
    load_snapshot_file,
    read_contained_graph_file,
)
from archsift.markdown_report import render_markdown_decision_report
from archsift.masking import masked_canonical_decision_record_bytes
from archsift.method import METHOD_SPECIFICATION, METHOD_VERSION, method_metadata
from archsift.method_review import validate_method_review_results
from archsift.persistence import (
    RecordPersistenceError,
    RecordPersistenceFailure,
    persist_decision_outputs,
    persist_report_output,
    report_target_name,
)
from archsift.pptx_report import render_executive_pptx_report
from archsift.registration import (
    MaterialRegistration,
    RegistrationError,
    RegistrationFailure,
    register_document,
    register_repository,
)
from archsift.rules import (
    RULESET_VERSION,
    list_rules,
)
from archsift.usability import validate_usability_results
from archsift.validation import (
    LATEST_DOSSIER_SCHEMA_VERSION,
    SUPPORTED_DOSSIER_SCHEMA_VERSIONS,
    ValidationResult,
    evaluate_agency_necessity_readiness,
    evaluate_autonomy_permission_readiness,
    evaluate_candidate_comparison_readiness,
    evaluate_consistency_readiness,
    evaluate_problem_value_readiness,
    validate_workspace,
)
from archsift.vocabulary import (
    VOCABULARY_SPECIFICATION,
    VOCABULARY_VERSION,
    VocabularyError,
    framework_rule_number,
    phrase,
    rule_phrases,
    vocabulary_payload,
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

    schema_parser = subparsers.add_parser(
        "dossier-schema",
        help="emit one complete packaged dossier JSON Schema",
    )
    schema_parser.add_argument(
        "--schema-version",
        type=int,
        choices=SUPPORTED_DOSSIER_SCHEMA_VERSIONS,
        default=LATEST_DOSSIER_SCHEMA_VERSION,
        help="supported dossier schema version; defaults to the latest",
    )
    schema_parser.add_argument(
        "--evidence-set",
        action="store_true",
        help="emit the evidence-set profile of the selected schema version instead of the schema",
    )
    _output_options(schema_parser)

    prerequisites_parser = subparsers.add_parser(
        "prerequisites",
        help="emit the outstanding decision-prerequisite worklist",
    )
    prerequisites_parser.add_argument(
        "case",
        type=Path,
        help="workspace directory containing case.yaml",
    )
    _output_options(prerequisites_parser)

    document_parser = subparsers.add_parser(
        "register-document",
        help="copy one explicit document into the inert case-material store",
    )
    document_parser.add_argument("case", type=Path, help="existing case workspace")
    document_parser.add_argument("registration_id", help="portable immutable registration ID")
    document_parser.add_argument("declared_type", help="caller-declared material type")
    document_parser.add_argument("source", help="authorised-root-relative source path")
    document_parser.add_argument(
        "--external-material-root",
        type=Path,
        help="explicitly authorise one external source directory",
    )
    _output_options(document_parser)

    repository_parser = subparsers.add_parser(
        "register-repository",
        help="copy explicit repository files with caller-supplied commit provenance",
    )
    repository_parser.add_argument("case", type=Path, help="existing case workspace")
    repository_parser.add_argument("registration_id", help="portable immutable registration ID")
    repository_parser.add_argument("declared_type", help="caller-declared repository type")
    repository_parser.add_argument(
        "--commit",
        required=True,
        help="full lowercase SHA-1 or SHA-256 commit identity",
    )
    repository_parser.add_argument(
        "--file",
        action="append",
        required=True,
        dest="files",
        help="explicit repository-relative regular file; repeat for each file",
    )
    repository_parser.add_argument(
        "--external-material-root",
        type=Path,
        help="explicitly authorise one external repository directory",
    )
    _output_options(repository_parser)

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
    assess_parser.add_argument(
        "--graph-snapshot",
        type=Path,
        help="canonical published graph snapshot supporting emitted findings",
    )
    assess_parser.add_argument(
        "--graph-request",
        type=Path,
        help="canonical private case-view request paired with --graph-snapshot",
    )
    _output_options(assess_parser)

    report_parser = subparsers.add_parser(
        "report", help="render a report from an immutable canonical decision record"
    )
    report_parser.add_argument("record", type=Path, help="canonical decision-record JSON")
    report_parser.add_argument(
        "--format",
        choices=("html", "pptx"),
        default="html",
        dest="report_format",
        help="rendered report format",
    )
    report_parser.add_argument(
        "--level",
        choices=("detailed", "executive"),
        default="detailed",
        help="rendered report level",
    )
    _output_options(report_parser)

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

    authoring_results_parser = subparsers.add_parser(
        "authoring-results", help="validate one simulated assisted-authoring result cohort"
    )
    authoring_results_parser.add_argument(
        "results", type=Path, help="completed authoring-results JSON"
    )
    _output_options(authoring_results_parser)

    method_review_parser = subparsers.add_parser(
        "method-review-results", help="validate one independent architecture-method review result"
    )
    method_review_parser.add_argument(
        "results", type=Path, help="completed method-review-results JSON"
    )
    _output_options(method_review_parser)

    graph_snapshot_parser = subparsers.add_parser(
        "graph-snapshot", help="validate one published knowledge-graph snapshot"
    )
    graph_snapshot_parser.add_argument(
        "snapshot", type=Path, help="canonical knowledge-graph snapshot JSON"
    )
    _output_options(graph_snapshot_parser)

    graph_view_parser = subparsers.add_parser(
        "graph-view", help="construct one deterministic private graph case view"
    )
    graph_view_parser.add_argument("snapshot", type=Path, help="canonical graph snapshot JSON")
    graph_view_parser.add_argument("request", type=Path, help="canonical private case-view request")
    _output_options(graph_view_parser)

    graph_change_parser = subparsers.add_parser(
        "graph-change", help="validate evidence-backed knowledge-graph evolution"
    )
    graph_change_parser.add_argument(
        "proposal", type=Path, help="canonical graph-change proposal JSON"
    )
    graph_change_parser.add_argument(
        "proposed_snapshot", type=Path, help="canonical proposed graph snapshot JSON"
    )
    graph_change_parser.add_argument(
        "--base-snapshot", type=Path, help="exact immutable base graph snapshot"
    )
    _output_options(graph_change_parser)

    graph_corpus_parser = subparsers.add_parser(
        "graph-corpus", help="inspect or emit the packaged architecture knowledge corpus"
    )
    _output_options(graph_corpus_parser)
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
    advisories: tuple[Diagnostic, ...] = (),
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
        # Advisories are distinct from failures: they follow the success line
        # on stdout and never change the exit status (FR-012).
        for advisory in advisories:
            _print(f"advisory: {advisory.render()}", stream=sys.stdout)


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
        prerequisites = evaluate_assessment(result.dossier).prerequisite_evaluation
        details["assessment_prerequisites_ready"] = prerequisites.ready
        details["prerequisite_finding_count"] = len(prerequisites.findings)
        details["ruleset_version"] = prerequisites.ruleset_version
        details["schema_version"] = result.dossier.schema_version
        details["task_defined"] = result.dossier.task is not None
    details["advisories"] = [advisory.to_dict() for advisory in result.advisories]
    declared = result.dossier.schema_version if result.dossier is not None else None
    _emit(
        status=status,
        exit_code=result.exit_code,
        diagnostics=result.diagnostics,
        json_output=json_output,
        quiet=quiet,
        success_message=f"Valid case file: case.yaml (format {declared})",
        details=details,
        advisories=result.advisories,
    )
    return int(result.exit_code)


def _run_dossier_schema(
    schema_version: int,
    *,
    evidence_set: bool = False,
    json_output: bool,
    quiet: bool,
) -> int:
    if evidence_set:
        return _run_evidence_set_profile(schema_version, json_output=json_output, quiet=quiet)
    try:
        surface = dossier_schema_surface(schema_version)
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)
    if quiet:
        return int(ExitCode.SUCCESS)
    if json_output:
        _write_canonical_stdout(surface.canonical_bytes)
        return int(ExitCode.SUCCESS)
    _print(
        f"Dossier schema {surface.schema_version}: {surface.content_identity}; "
        f"{len(surface.top_level_properties)} top-level properties; "
        f"{surface.definition_count} definitions",
        stream=sys.stdout,
    )
    return int(ExitCode.SUCCESS)


def _run_evidence_set_profile(schema_version: int, *, json_output: bool, quiet: bool) -> int:
    """Emit the evidence-set profile (FR-021) of one supported dossier schema version."""
    try:
        validate_slot_coverage()
        profile = evidence_set_profile(schema_version)
        content = profile_bytes(profile)
        lines = profile_lines(profile)
    except Exception as error:  # a packaging defect, never a case defect
        return _internal_error(error, json_output=json_output, quiet=quiet)
    if quiet:
        return int(ExitCode.SUCCESS)
    if json_output:
        _write_canonical_stdout(content)
        return int(ExitCode.SUCCESS)
    for line in lines:
        _print(line, stream=sys.stdout)
    return int(ExitCode.SUCCESS)


def _run_prerequisites(path: Path, *, json_output: bool, quiet: bool) -> int:
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
        worklist = prerequisite_worklist(result.dossier)
        content = canonical_json_bytes(worklist)
        # The machine-readable worklist never depends on the vocabulary; only
        # the human rendering does, and it fails closed on an unmapped rule.
        human = [] if json_output or quiet else _human_worklist(worklist)
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)
    if quiet:
        return int(ExitCode.SUCCESS)
    if json_output:
        _write_canonical_stdout(content)
        return int(ExitCode.SUCCESS)
    for line in human:
        _print(line, stream=sys.stdout)
    return int(ExitCode.SUCCESS)


def _human_worklist(worklist: JsonObject) -> list[str]:
    """Render the outstanding worklist in the plain-language register (NFR-011).

    The readiness line and each gap speak through the vocabulary: the flag and
    what would settle it. Human mode never renders authored text, so a gap
    names no element; its rule identifier and field path follow as the FR-012
    trace, clearly separated, so the gap stays locatable.
    """
    findings = cast(list[JsonObject], worklist["findings"])
    versions = (
        f"case file format {worklist['dossier_schema_version']}; "
        f"rules {worklist['ruleset_version']}"
    )
    if not findings:
        return [f"Ready for assessment: no gaps outstanding ({versions})."]
    count = "1 gap" if len(findings) == 1 else f"{len(findings)} gaps"
    lines = [f"Not yet ready for assessment: {count} outstanding ({versions})."]
    for finding in findings:
        rule_id = cast(str, finding["rule_id"])
        phrases = rule_phrases(rule_id)
        lines.append(
            f"{phrases.flag} flag: {phrases.remediation} [trace: {rule_id} {finding['field']}]"
        )
    return lines


_REGISTRATION_UNAVAILABLE = {
    RegistrationFailure.ROOT_UNAVAILABLE,
    RegistrationFailure.TARGET_MISSING,
    RegistrationFailure.TARGET_UNREADABLE,
}
_REGISTRATION_UNSAFE = {
    RegistrationFailure.PATH_UNSAFE,
    RegistrationFailure.TARGET_NOT_REGULAR,
    RegistrationFailure.TARGET_CHANGED,
}


def _run_registration(
    operation: Callable[[], MaterialRegistration],
    *,
    json_output: bool,
    quiet: bool,
) -> int:
    try:
        registration = operation()
    except RegistrationError as error:
        if error.category in _REGISTRATION_UNAVAILABLE:
            exit_code = ExitCode.ARTEFACT_UNAVAILABLE
            status = "artefact-unavailable"
        elif error.category in _REGISTRATION_UNSAFE:
            exit_code = ExitCode.UNSAFE_PATH
            status = "unsafe"
        elif error.category is RegistrationFailure.PUBLISH_FAILED:
            exit_code = ExitCode.PERSISTENCE_FAILED
            status = "persistence-failed"
        else:
            exit_code = ExitCode.VALIDATION_FAILED
            status = "invalid"
        diagnostic = Diagnostic(
            id=f"material-registration-{error.category.value}",
            message=error.message,
            file="evidence/registered",
            field=error.field,
            requirement="FR-018/NFR-004",
            remediation=(
                "Use explicit, unique regular-file inputs beneath the authorised root and a "
                "new registration ID when material differs."
            ),
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
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)
    _emit(
        status="registered",
        exit_code=ExitCode.SUCCESS,
        diagnostics=(),
        json_output=json_output,
        quiet=quiet,
        success_message=(
            f"Registered inert {registration.registration_kind.value} material: "
            f"{registration.registration_id} ({registration.registration_content_identity})"
        ),
        details={
            "declared_type": registration.declared_type,
            "file_count": len(registration.files),
            "registration_content_identity": registration.registration_content_identity,
            "registration_id": registration.registration_id,
            "registration_kind": registration.registration_kind.value,
            "repository_commit": registration.repository_commit,
        },
    )
    return int(ExitCode.SUCCESS)


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
    graph_snapshot_path: Path | None,
    graph_request_path: Path | None,
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
        case_view = None
        if graph_snapshot_path is not None and graph_request_path is not None:
            try:
                snapshot = load_snapshot_file(graph_snapshot_path, root=Path("."))
            except (SnapshotError, SnapshotFileError) as error:
                return _emit_graph_input_failure(
                    error,
                    path=graph_snapshot_path,
                    json_output=json_output,
                    quiet=quiet,
                    command="assess-graph",
                    requirement="FR-011/FR-015",
                )
            try:
                request = load_case_view_request(
                    read_contained_graph_file(graph_request_path, root=Path("."))
                )
                case_view = construct_case_view(snapshot, request)
            except (CaseViewError, SnapshotFileError) as error:
                return _emit_graph_input_failure(
                    error,
                    path=graph_request_path,
                    json_output=json_output,
                    quiet=quiet,
                    command="assess-graph",
                    requirement="FR-011/FR-015",
                )
        try:
            record = compose_decision_record(
                result.dossier,
                tool_version=package_version(),
                artefact_identities=artefacts,
                case_view=case_view,
            )
        except DecisionRecordError as error:
            if case_view is None:
                raise
            diagnostic = Diagnostic(
                id="assess-graph-invalid-binding",
                message=str(error),
                file=str(graph_request_path),
                field="$.finding_ids",
                requirement="FR-011/FR-015",
                remediation=(
                    "Bind only finding IDs that exactly match rule IDs emitted by this assessment "
                    "and include at least one complete reusable claim-to-rule trace."
                ),
            )
            _emit(
                status="invalid",
                exit_code=ExitCode.VALIDATION_FAILED,
                diagnostics=(diagnostic,),
                json_output=json_output,
                quiet=quiet,
                success_message="",
                details={},
            )
            return int(ExitCode.VALIDATION_FAILED)
        content = masked_canonical_decision_record_bytes(record)
        report = render_markdown_decision_report(record)
        persisted = persist_decision_outputs(path, record, content, report)
        result_line = _human_result(record.assessment.verdict, record.assessment.recommended_class)
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
        f"{result_line} Record {record.record_content_identity} "
        f"-> {persisted.json.relative_path}; report -> {persisted.markdown.relative_path}",
        stream=sys.stdout,
    )
    return int(ExitCode.SUCCESS)


def _human_result(verdict: ArchitectureVerdict, recommended: object) -> str:
    """Return the result, and the indicated option when there is one, as vocabulary phrases."""
    text = phrase(verdict)
    line = f"Result: {text[0].upper()}{text[1:]}."
    if recommended is not None:
        line += f" Indicated option: {phrase(recommended)}."
    return line


def _emit_record_input_failure(
    error: ComparisonInputError,
    *,
    command: str,
    file: str,
    requirement: str,
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
        id=f"{command}-{error.category.value}",
        message=error.message,
        file=file,
        field=error.field,
        requirement=requirement,
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


def _emit_compare_failure(
    error: ComparisonInputError,
    *,
    json_output: bool,
    quiet: bool,
) -> int:
    return _emit_record_input_failure(
        error,
        command="compare",
        file=f"{error.role}-record",
        requirement="FR-013",
        json_output=json_output,
        quiet=quiet,
    )


def _reported_output_path(root: Path, directory: Path, filename: str) -> str:
    """Return one generated output's authorised-root-relative POSIX path."""
    return (directory.relative_to(root.resolve(strict=True)) / filename).as_posix()


# The report surface a record can be rendered into. FR-016 defines the detailed
# report in HTML; FR-017 defines the executive summary in HTML and PPTX. A
# combination absent here has no renderer and is refused as a usage error.
_REPORT_RENDERERS: dict[tuple[str, str], Callable[[JsonObject], bytes]] = {
    ("html", "detailed"): render_detailed_html_report,
    ("html", "executive"): render_executive_html_report,
    ("pptx", "executive"): render_executive_pptx_report,
}


def _run_report(
    path: Path,
    *,
    report_format: str,
    level: str,
    json_output: bool,
    quiet: bool,
) -> int:
    try:
        root = Path(".")
        # The record is resolved once at the shared safe-read boundary; its
        # containing directory is therefore already proven to sit inside the
        # authorised root and is where the rendered report is written.
        resolved = resolve_record_path(path, root=root, role="record")
        record = load_decision_record(resolved, root=root, role="record")
        identity = record["record_content_identity"]
        if type(identity) is not str:
            raise ValueError("loaded record has no content identity")
        content = _REPORT_RENDERERS[(report_format, level)](record)
        filename = report_target_name(identity, level, report_format)
        directory = resolved.parent
        persisted = persist_report_output(
            directory,
            filename,
            content,
            reported_path=_reported_output_path(root, directory, filename),
        )
    except ComparisonInputError as error:
        return _emit_record_input_failure(
            error,
            command="report",
            file="record",
            requirement="FR-016",
            json_output=json_output,
            quiet=quiet,
        )
    except RecordPersistenceError as error:
        return _emit_assess_failure(error, json_output=json_output, quiet=quiet)
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)

    _emit(
        status="rendered",
        exit_code=ExitCode.SUCCESS,
        diagnostics=(),
        json_output=json_output,
        quiet=quiet,
        success_message=(
            f"Rendered {level} {report_format} report: {identity} -> {persisted.relative_path}"
        ),
        details={
            "format": report_format,
            "level": level,
            "record_content_identity": identity,
            "report": persisted.relative_path,
            "reused": persisted.reused,
        },
    )
    return int(ExitCode.SUCCESS)


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


def _run_authoring_results(path: Path, *, json_output: bool, quiet: bool) -> int:
    try:
        result = validate_authoring_results(path)
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)
    status = "criterion-met" if result.exit_code is ExitCode.SUCCESS else "invalid"
    if any(item.id == "authoring-threshold-not-met" for item in result.diagnostics):
        status = "criterion-not-met"
    _emit(
        status=status,
        exit_code=result.exit_code,
        diagnostics=result.diagnostics,
        json_output=json_output,
        quiet=quiet,
        success_message=(
            f"Assisted-authoring criterion met: {result.passed_session_count} of "
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


def _run_method_review_results(path: Path, *, json_output: bool, quiet: bool) -> int:
    try:
        result = validate_method_review_results(path)
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)
    status = "criterion-met" if result.criterion_met else "invalid"
    if any(item.id == "method-review-criterion-not-met" for item in result.diagnostics):
        status = "criterion-not-met"
    if result.binding_superseded and status != "invalid":
        status = f"{status}-superseded"
    covered = result.binding.render() if result.binding is not None else "an unknown binding"
    scope = (
        f"criterion met for superseded binding ({covered})"
        if result.binding_superseded
        else "criterion met"
    )
    if result.binding_superseded and result.diagnostics and not quiet and not json_output:
        # _emit renders diagnostics instead of the summary line, so the covered
        # binding would otherwise be invisible in human mode.
        _print(f"Result covers superseded binding: {covered}", stream=sys.stdout)
    details: dict[str, object] = {
        "criterion_met": result.criterion_met,
        "disagreement_count": result.disagreement_count,
        "example_count": result.example_count,
        "protocol_version": result.protocol_version,
        **(
            {
                "session_count": result.session_count,
                "passed_session_count": result.passed_session_count,
            }
            if result.protocol_version == "2.0.0"
            else {}
        ),
    }
    if result.binding_superseded:
        details.update(
            {
                "binding_state": "superseded",
                "corpus_version": result.binding.corpus_version if result.binding else None,
                "method_version": result.binding.method_version if result.binding else None,
                "ruleset_version": result.binding.ruleset_version if result.binding else None,
            }
        )
    _emit(
        status=status,
        exit_code=result.exit_code,
        diagnostics=result.diagnostics,
        json_output=json_output,
        quiet=quiet,
        success_message=(
            f"Architecture-method review {scope}: {result.passed_session_count} of "
            f"{result.session_count} sessions passed (protocol {result.protocol_version})"
            if result.protocol_version == "2.0.0"
            else (
                f"Architecture-method review {scope}: {result.example_count} examples "
                f"reviewed (protocol {result.protocol_version})"
            )
        ),
        details=details,
    )
    return int(result.exit_code)


def _run_graph_snapshot(path: Path, *, json_output: bool, quiet: bool) -> int:
    try:
        snapshot = load_snapshot_file(path, root=Path("."))
    except (SnapshotError, SnapshotFileError) as error:
        exit_code = error.exit_code
        status = {
            ExitCode.MALFORMED_INPUT: "malformed",
            ExitCode.UNSUPPORTED_SCHEMA: "unsupported",
            ExitCode.VALIDATION_FAILED: "invalid",
            ExitCode.UNSAFE_PATH: "unsafe",
            ExitCode.ARTEFACT_UNAVAILABLE: "artefact-unavailable",
        }[exit_code]
        diagnostic = Diagnostic(
            id=f"graph-snapshot-{error.category.value}",
            message=error.message,
            file=str(path),
            field=error.field,
            requirement="FR-015",
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
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)

    node_counts = Counter(node.kind.value for node in snapshot.nodes)
    relation_counts = Counter(relation.kind.value for relation in snapshot.relations)
    details: dict[str, object] = {
        "file": str(path),
        "graph_schema_version": snapshot.graph_schema_version,
        "graph_version": snapshot.graph_version,
        "node_count": len(snapshot.nodes),
        "node_counts_by_kind": {kind.value: node_counts[kind.value] for kind in NodeKind},
        "relation_count": len(snapshot.relations),
        "relation_counts_by_kind": {
            kind.value: relation_counts[kind.value] for kind in RelationKind
        },
        "snapshot_content_identity": snapshot.snapshot_content_identity,
    }
    _emit(
        status="valid",
        exit_code=ExitCode.SUCCESS,
        diagnostics=(),
        json_output=json_output,
        quiet=quiet,
        success_message=(
            f"Valid graph snapshot: schema {snapshot.graph_schema_version}; "
            f"graph {snapshot.graph_version}; snapshot {snapshot.snapshot_content_identity}; "
            f"{len(snapshot.nodes)} nodes; {len(snapshot.relations)} relations"
        ),
        details=details,
    )
    return int(ExitCode.SUCCESS)


def _emit_graph_input_failure(
    error: SnapshotError | SnapshotFileError | CaseViewError | GraphChangeError,
    *,
    path: Path,
    json_output: bool,
    quiet: bool,
    command: str = "graph-view",
    requirement: str = "FR-015",
) -> int:
    exit_code = error.exit_code
    status = {
        ExitCode.MALFORMED_INPUT: "malformed",
        ExitCode.UNSUPPORTED_SCHEMA: "unsupported",
        ExitCode.VALIDATION_FAILED: "invalid",
        ExitCode.UNSAFE_PATH: "unsafe",
        ExitCode.ARTEFACT_UNAVAILABLE: "artefact-unavailable",
    }[exit_code]
    diagnostic = Diagnostic(
        id=f"{command}-{error.category.value}",
        message=error.message,
        file=str(path),
        field=error.field,
        requirement=requirement,
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


def _run_graph_view(
    snapshot_path: Path,
    request_path: Path,
    *,
    json_output: bool,
    quiet: bool,
) -> int:
    root = Path(".")
    try:
        snapshot = load_snapshot_file(snapshot_path, root=root)
    except (SnapshotError, SnapshotFileError) as error:
        return _emit_graph_input_failure(
            error, path=snapshot_path, json_output=json_output, quiet=quiet
        )
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)
    try:
        request = load_case_view_request(read_contained_graph_file(request_path, root=root))
        view = construct_case_view(snapshot, request)
    except (CaseViewError, SnapshotFileError) as error:
        return _emit_graph_input_failure(
            error, path=request_path, json_output=json_output, quiet=quiet
        )
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)

    traces = view.content["reusable_claim_traces"]
    conflicts = view.content["conflict_relation_ids"]
    gaps = view.content["reusable_knowledge_gap_claim_ids"]
    findings = view.content["case_finding_ids"]
    if not all(type(value) is list for value in (traces, conflicts, gaps, findings)):
        return _internal_error(
            ValueError("case-view count contract"), json_output=json_output, quiet=quiet
        )
    trace_items = cast(list[object], traces)
    conflict_items = cast(list[object], conflicts)
    gap_items = cast(list[object], gaps)
    finding_items = cast(list[object], findings)
    _emit(
        status="valid",
        exit_code=ExitCode.SUCCESS,
        diagnostics=(),
        json_output=json_output,
        quiet=quiet,
        success_message=(
            f"Graph case view {view.content_identity}: {len(trace_items)} traces; "
            f"{len(conflict_items)} conflicts; {len(gap_items)} reusable-knowledge gaps; "
            f"{len(finding_items)} private findings; graph {snapshot.graph_version}"
        ),
        details={"case_view": view.content, "case_view_content_identity": view.content_identity},
    )
    return int(ExitCode.SUCCESS)


def _run_graph_change(
    proposal_path: Path,
    proposed_path: Path,
    base_path: Path | None,
    *,
    json_output: bool,
    quiet: bool,
) -> int:
    root = Path(".")
    try:
        proposal = load_graph_change_proposal(read_contained_graph_file(proposal_path, root=root))
    except (GraphChangeError, SnapshotFileError) as error:
        return _emit_graph_input_failure(
            error,
            path=proposal_path,
            json_output=json_output,
            quiet=quiet,
            command="graph-change",
            requirement="FR-014/FR-015",
        )
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)
    try:
        proposed = load_snapshot_file(proposed_path, root=root)
    except (SnapshotError, SnapshotFileError) as error:
        return _emit_graph_input_failure(
            error,
            path=proposed_path,
            json_output=json_output,
            quiet=quiet,
            command="graph-change",
            requirement="FR-014/FR-015",
        )
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)
    try:
        base = None if base_path is None else load_snapshot_file(base_path, root=root)
    except (SnapshotError, SnapshotFileError) as error:
        return _emit_graph_input_failure(
            error,
            path=cast(Path, base_path),
            json_output=json_output,
            quiet=quiet,
            command="graph-change",
            requirement="FR-014/FR-015",
        )
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)
    try:
        summary = validate_graph_change(proposal, proposed, base)
    except GraphChangeError as error:
        return _emit_graph_input_failure(
            error,
            path=proposal_path,
            json_output=json_output,
            quiet=quiet,
            command="graph-change",
            requirement="FR-014/FR-015",
        )
    except Exception as error:  # defensive CLI boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)

    node_counts = cast(dict[str, int], summary["node_changes"])
    relation_counts = cast(dict[str, int], summary["relation_changes"])
    base_identity = "none"
    if base is not None:
        base_identity = base.snapshot_content_identity
    _emit(
        status="valid",
        exit_code=ExitCode.SUCCESS,
        diagnostics=(),
        json_output=json_output,
        quiet=quiet,
        success_message=(
            f"Valid graph change {summary['change_id']}: base {base_identity}; "
            f"proposed {proposed.snapshot_content_identity}; "
            f"nodes +{node_counts['added']} ~{node_counts['changed']} "
            f"-{node_counts['removed']}; relations +{relation_counts['added']} "
            f"~{relation_counts['changed']} -{relation_counts['removed']}"
        ),
        details={"graph_change": summary},
    )
    return int(ExitCode.SUCCESS)


def _run_graph_corpus(*, json_output: bool, quiet: bool) -> int:
    try:
        snapshot = packaged_corpus_snapshot()
        content = packaged_corpus_bytes()
    except Exception as error:  # packaged-integrity boundary
        return _internal_error(error, json_output=json_output, quiet=quiet)
    if quiet:
        return int(ExitCode.SUCCESS)
    if json_output:
        _write_canonical_stdout(content)
        return int(ExitCode.SUCCESS)
    node_counts = Counter(node.kind.value for node in snapshot.nodes)
    relation_counts = Counter(relation.kind.value for relation in snapshot.relations)
    _print(
        (
            f"Packaged graph corpus: schema {snapshot.graph_schema_version}; "
            f"graph {snapshot.graph_version}; snapshot {snapshot.snapshot_content_identity}; "
            f"{len(snapshot.nodes)} nodes across "
            f"{sum(1 for count in node_counts.values() if count)} kinds; "
            f"{len(snapshot.relations)} relations across "
            f"{sum(1 for count in relation_counts.values() if count)} kinds"
        ),
        stream=sys.stdout,
    )
    return int(ExitCode.SUCCESS)


def _run_rules(*, json_output: bool, quiet: bool) -> int:
    rules = list_rules()
    try:
        vocabulary = vocabulary_payload()
        card = card_lines(build_framework_card())
        numbers = {rule.id: framework_rule_number(rule.id) for rule in rules}
    except VocabularyError as error:  # a packaging defect, never a case defect
        return _internal_error(error, json_output=json_output, quiet=quiet)
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
                vocabulary=vocabulary,
            ),
            stream=sys.stdout,
        )
        return int(ExitCode.SUCCESS)
    _print(
        f"ArchSift ruleset {RULESET_VERSION} (method {METHOD_VERSION}; {METHOD_SPECIFICATION})",
        stream=sys.stdout,
    )
    _print(
        f"Plain-language vocabulary {VOCABULARY_VERSION} ({VOCABULARY_SPECIFICATION}); "
        "findings read as flags: stop, gap, condition, fit, noted",
        stream=sys.stdout,
    )
    for line in card:
        _print(line, stream=sys.stdout)
    for rule in rules:
        phrases = rule_phrases(rule.id)
        _print(
            f"{rule.id} [{rule.effect.value}; {rule.requirement}] {rule.description} "
            f"Consequence: {rule.consequence} Rationale: {rule.source_rationale} "
            f"Method: {rule.rationale_id} Sources: {','.join(rule.source_ids)} "
            f"Flag: {phrases.flag}. Reads: {phrases.consequence} "
            f"Framework rule {numbers[rule.id]}.",
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
    if args.command == "dossier-schema":
        return _run_dossier_schema(
            args.schema_version,
            evidence_set=args.evidence_set,
            json_output=args.json_output,
            quiet=args.quiet,
        )
    if args.command == "prerequisites":
        return _run_prerequisites(
            args.case,
            json_output=args.json_output,
            quiet=args.quiet,
        )
    if args.command == "register-document":
        return _run_registration(
            lambda: register_document(
                args.case,
                args.registration_id,
                args.declared_type,
                args.source,
                external_material_root=args.external_material_root,
            ),
            json_output=args.json_output,
            quiet=args.quiet,
        )
    if args.command == "register-repository":
        return _run_registration(
            lambda: register_repository(
                args.case,
                args.registration_id,
                args.declared_type,
                args.commit,
                tuple(args.files),
                external_material_root=args.external_material_root,
            ),
            json_output=args.json_output,
            quiet=args.quiet,
        )
    if args.command == "rules":
        return _run_rules(json_output=args.json_output, quiet=args.quiet)
    if args.command == "assess":
        if (args.graph_snapshot is None) != (args.graph_request is None):
            parser.error("--graph-snapshot and --graph-request must be supplied together")
        return _run_assess(
            args.case,
            external_evidence_root=args.external_evidence_root,
            graph_snapshot_path=args.graph_snapshot,
            graph_request_path=args.graph_request,
            json_output=args.json_output,
            quiet=args.quiet,
        )
    if args.command == "report":
        if (args.report_format, args.level) not in _REPORT_RENDERERS:
            _usage_error(
                parser,
                f"--format {args.report_format} does not support --level {args.level}",
            )
        return _run_report(
            args.record,
            report_format=args.report_format,
            level=args.level,
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
    if args.command == "authoring-results":
        return _run_authoring_results(
            args.results,
            json_output=args.json_output,
            quiet=args.quiet,
        )
    if args.command == "method-review-results":
        return _run_method_review_results(
            args.results,
            json_output=args.json_output,
            quiet=args.quiet,
        )
    if args.command == "graph-snapshot":
        return _run_graph_snapshot(
            args.snapshot,
            json_output=args.json_output,
            quiet=args.quiet,
        )
    if args.command == "graph-view":
        return _run_graph_view(
            args.snapshot,
            args.request,
            json_output=args.json_output,
            quiet=args.quiet,
        )
    if args.command == "graph-change":
        return _run_graph_change(
            args.proposal,
            args.proposed_snapshot,
            args.base_snapshot,
            json_output=args.json_output,
            quiet=args.quiet,
        )
    if args.command == "graph-corpus":
        return _run_graph_corpus(json_output=args.json_output, quiet=args.quiet)
    parser.print_help()
    return int(ExitCode.SUCCESS)
