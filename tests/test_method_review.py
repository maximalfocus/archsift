from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.method import METHOD_VERSION
from archsift.method_review import (
    CORPUS_VERSION,
    FAILURE_REASONS,
    PROTOCOL_VERSION,
    REQUIRED_DECISION_AREAS,
    REQUIRED_EXAMPLES,
    RESULT_SCHEMA_VERSION,
    SUPPORTED_ARCHSIFT_VERSION,
    validate_method_review_results,
)
from archsift.rules import RULESET_VERSION

_TRACE_RULES = {
    "problem-value": "binding-outcome-met",
    "agency-necessity": "agentic-runtime-adaptation-supports-agency",
    "autonomy-permission": "mandatory-human-control-retained",
    "comparative-fit": "binding-constraint-met",
}
_TRACE_EVIDENCE = {
    "problem-value": "decision-observed",
    "agency-necessity": "agency-observed",
    "autonomy-permission": "autonomy-observed",
    "comparative-fit": "decision-observed",
}


def _area(name: str, *, outcome: str = "causal") -> dict[str, Any]:
    rule_id = _TRACE_RULES[name]
    if outcome == "explicitly-non-decisive":
        rule_id = "agentic-agency-fact-non-decisive"
    return {
        "decision_area": name,
        "trace_outcome": outcome,
        "rule_ids": [rule_id],
        "evidence_ids": [_TRACE_EVIDENCE[name]],
        "candidate_ids": [] if outcome == "display-only" else ["reviewed-candidate"],
        "verdict_rule_id": None if outcome == "display-only" else "verdict-supported",
    }


def _example(index: int, example_id: str) -> dict[str, Any]:
    areas = [_area(name) for name in REQUIRED_DECISION_AREAS]
    if index == 1:
        areas[1] = _area("agency-necessity", outcome="explicitly-non-decisive")
    return {
        "example_id": example_id,
        "decision_record_identity": f"sha256:{index:064x}",
        "decision_areas": areas,
        "example_result": "pass",
    }


def _review() -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "archsift_version_or_commit": SUPPORTED_ARCHSIFT_VERSION,
        "method_version": METHOD_VERSION,
        "ruleset_version": RULESET_VERSION,
        "corpus_version": CORPUS_VERSION,
        "reviewer": {
            "reviewer_id": "reviewer-01",
            "target_reviewer_eligible": True,
            "independent": True,
            "environment": {
                "operating_system": "linux",
                "python_version": "3.11",
                "install_mode": "built-wheel",
            },
        },
        "maintainer_intervention": False,
        "examples": [
            _example(index, example_id)
            for index, example_id in enumerate(REQUIRED_EXAMPLES, start=1)
        ],
        "disagreements": [],
        "overall_result": "met",
        "failure_reasons": [],
    }


def _disagreement(classification: str, *, critical: bool) -> dict[str, Any]:
    return {
        "disagreement_id": "disagreement-01",
        "example_id": "agentic-control",
        "decision_area": "agency-necessity",
        "classification": classification,
        "decision_critical": critical,
        "evidence_ids": ["agency-observed"] if classification == "declared-evidence" else [],
        "rule_ids": (
            ["agentic-runtime-adaptation-supports-agency"]
            if classification == "public-rule"
            else []
        ),
        "product_gap_id": "gap-trace-coverage" if classification == "product-gap" else None,
    }


def _write_result(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def test_packaged_schema_and_corpus_bindings_are_valid() -> None:
    root = Path(__file__).parents[1]
    schema_path = root / "src/archsift/schemas/method-review-results-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    manifest = json.loads((root / "examples/manifest.json").read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["schema_version"]["const"] == RESULT_SCHEMA_VERSION
    assert schema["properties"]["protocol_version"]["const"] == PROTOCOL_VERSION
    assert schema["properties"]["archsift_version_or_commit"]["oneOf"][0]["const"] == (
        SUPPORTED_ARCHSIFT_VERSION
    )
    assert schema["properties"]["method_version"]["const"] == METHOD_VERSION
    assert schema["properties"]["ruleset_version"]["const"] == RULESET_VERSION
    assert schema["properties"]["corpus_version"]["const"] == CORPUS_VERSION
    assert manifest["corpus_version"] == CORPUS_VERSION
    assert tuple(item["path"] for item in manifest["examples"]) == REQUIRED_EXAMPLES
    example_ids = schema["$defs"]["exampleId"]["enum"]
    assert tuple(example_ids) == REQUIRED_EXAMPLES
    decision_areas = schema["$defs"]["decisionArea"]["enum"]
    assert tuple(decision_areas) == REQUIRED_DECISION_AREAS
    failure_reasons = schema["properties"]["failure_reasons"]["items"]["enum"]
    assert tuple(failure_reasons) == FAILURE_REASONS


def test_complete_review_meets_criterion(tmp_path: Path) -> None:
    path = tmp_path / "method-review-results.json"
    _write_result(path, _review())

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.protocol_version == PROTOCOL_VERSION
    assert result.example_count == 4
    assert result.disagreement_count == 0
    assert result.criterion_met is True
    assert result.diagnostics == ()


def test_public_source_commit_binding_is_supported(tmp_path: Path) -> None:
    payload = _review()
    payload["archsift_version_or_commit"] = "6517a88995715f710d7e3b2ec4796e4cb51cdd5d"
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.SUCCESS


def test_cli_reports_success_in_human_and_json_modes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "method-review-results.json"
    _write_result(path, _review())

    assert main(["method-review-results", str(path)]) == ExitCode.SUCCESS
    assert capsys.readouterr().out == (
        "Architecture-method review criterion met: 4 examples reviewed (protocol 1.0.0)\n"
    )

    assert main(["method-review-results", str(path), "--json"]) == ExitCode.SUCCESS
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "criterion_met": True,
        "diagnostics": [],
        "disagreement_count": 0,
        "example_count": 4,
        "exit_code": 0,
        "protocol_version": "1.0.0",
        "status": "criterion-met",
    }


def test_missing_corpus_example_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"].pop()
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-results-contract"


def test_duplicate_corpus_example_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][3]["example_id"] = "agentic-control"
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.criterion_met is False
    assert "method-review-example-set" in [item.id for item in result.diagnostics]


def test_duplicate_decision_record_identity_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][3]["decision_record_identity"] = payload["examples"][0][
        "decision_record_identity"
    ]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-record-duplicate"


def test_missing_decision_area_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"].pop()
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-results-contract"


def test_invalid_decision_area_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][0]["decision_area"] = "visibility"
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-results-contract"


def test_display_only_area_cannot_be_marked_successful(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][0] = _area("problem-value", outcome="display-only")
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert [item.id for item in result.diagnostics] == [
        "method-review-example-inconsistent",
        "method-review-failures-inconsistent",
        "method-review-overall-inconsistent",
        "method-review-criterion-not-met",
    ]


def test_unclassified_disagreement_cannot_be_marked_successful(tmp_path: Path) -> None:
    payload = _review()
    payload["disagreements"] = [_disagreement("unclassified", critical=False)]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-criterion-not-met" in [item.id for item in result.diagnostics]


def test_decision_critical_product_gap_cannot_be_marked_successful(tmp_path: Path) -> None:
    payload = _review()
    payload["disagreements"] = [_disagreement("product-gap", critical=True)]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-criterion-not-met" in [item.id for item in result.diagnostics]


def test_maintainer_intervention_cannot_be_marked_successful(tmp_path: Path) -> None:
    payload = _review()
    payload["maintainer_intervention"] = True
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-criterion-not-met" in [item.id for item in result.diagnostics]


def test_false_overall_success_claim_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][0] = _area("problem-value", outcome="display-only")
    payload["examples"][0]["example_result"] = "fail"
    payload["failure_reasons"] = ["display-only-decision-area"]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert [item.id for item in result.diagnostics] == [
        "method-review-overall-inconsistent",
        "method-review-criterion-not-met",
    ]


@pytest.mark.parametrize(
    ("field", "value", "diagnostic_id"),
    [
        ("schema_version", 2, "method-review-binding-unsupported"),
        ("protocol_version", "2.0.0", "method-review-binding-unsupported"),
        ("method_version", "2.0.0", "method-review-binding-unsupported"),
        ("ruleset_version", "2.0.0", "method-review-binding-unsupported"),
        ("corpus_version", "2.0.0", "method-review-binding-unsupported"),
        ("archsift_version_or_commit", "9.9.9", "method-review-tool-binding-unsupported"),
    ],
)
def test_version_binding_mismatch_is_unsupported(
    tmp_path: Path, field: str, value: object, diagnostic_id: str
) -> None:
    payload = _review()
    payload[field] = value
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.UNSUPPORTED_SCHEMA
    assert result.diagnostics[0].id == diagnostic_id


def test_invalid_tool_binding_is_unsupported(tmp_path: Path) -> None:
    payload = _review()
    payload["archsift_version_or_commit"] = "main"
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.UNSUPPORTED_SCHEMA
    assert result.diagnostics[0].id == "method-review-tool-binding-unsupported"


def test_inconsistent_disagreement_trace_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    disagreement = _disagreement("public-rule", critical=False)
    disagreement["evidence_ids"] = ["agency-observed"]
    payload["disagreements"] = [disagreement]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-disagreement-inconsistent"


def test_unknown_trace_rule_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][0]["rule_ids"] = ["unknown-rule"]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-rule-reference"


def test_strict_json_rejects_duplicate_object_key(tmp_path: Path) -> None:
    path = tmp_path / "method-review-results.json"
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "method-review-results-malformed"


def test_quiet_failure_emits_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = _review()
    payload["maintainer_intervention"] = True
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    assert main(["method-review-results", str(path), "--quiet"]) == ExitCode.VALIDATION_FAILED
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""


def test_public_docs_freeze_protocol_and_exact_offline_command() -> None:
    root = Path(__file__).parents[1]
    protocol = (root / "docs/method-review-v1.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    protocol_words = " ".join(protocol.split())

    assert "protocol 1.0.0" in protocol_words
    assert "method 1.2.0" in protocol_words
    assert "ruleset 1.8.0" in protocol_words
    assert "corpus 1.0.0" in protocol_words
    assert (
        "problem value, agency necessity, autonomy permission, and comparative fit"
        in protocol_words
    )
    assert "no independent review has been run" in protocol_words
    command = "archsift method-review-results method-review-results.json"
    assert command in protocol
    assert command in readme
    assert "docs/method-review-v1.md" in readme
