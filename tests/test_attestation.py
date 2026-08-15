from __future__ import annotations

import copy
from pathlib import Path

import yaml

from archsift.canonical import canonical_dossier_bytes
from archsift.comparison import compare_decision_records, load_decision_record
from archsift.decision import ArchitectureVerdict, evaluate_assessment
from archsift.decision_record import (
    canonical_decision_record_bytes,
    compose_decision_record,
)
from archsift.diagnostics import ExitCode
from archsift.markdown_report import render_markdown_decision_report
from archsift.validation import (
    EvidenceAuthor,
    EvidenceKind,
    validate_workspace,
)

_EXAMPLE = Path(__file__).parents[1] / "examples" / "fixed-workflow" / "case.yaml"


def _example() -> dict[str, object]:
    loaded = yaml.safe_load(_EXAMPLE.read_text(encoding="utf-8"))
    assert type(loaded) is dict
    return loaded


def _write(workspace: Path, dossier: dict[str, object]) -> None:
    workspace.mkdir()
    (workspace / "case.yaml").write_text(yaml.safe_dump(dossier, sort_keys=False), encoding="utf-8")


def _version_two(*, attested: bool | None = None) -> dict[str, object]:
    dossier = _example()
    dossier["schema_version"] = 2
    all_evidence = dossier["evidence"]
    assert type(all_evidence) is list
    for entry in all_evidence:
        assert type(entry) is dict
        entry["artefacts"] = []
    if attested is not None:
        evidence = all_evidence
        assert type(evidence) is list and type(evidence[0]) is dict
        evidence[0]["authorship"] = {
            "authored_by": "assistant",
            "attested_by_accountable_person": attested,
        }
    return dossier


def test_version_two_omission_and_explicit_human_attestation_are_canonically_equal(
    tmp_path: Path,
) -> None:
    omitted = _version_two()
    explicit = copy.deepcopy(omitted)
    evidence = explicit["evidence"]
    assert type(evidence) is list
    for entry in evidence:
        assert type(entry) is dict
        entry["authorship"] = {
            "authored_by": "accountable-person",
            "attested_by_accountable_person": True,
        }
    _write(tmp_path / "omitted", omitted)
    _write(tmp_path / "explicit", explicit)

    omitted_result = validate_workspace(tmp_path / "omitted")
    explicit_result = validate_workspace(tmp_path / "explicit")

    assert omitted_result.exit_code is ExitCode.SUCCESS
    assert explicit_result.exit_code is ExitCode.SUCCESS
    assert omitted_result.dossier is not None and explicit_result.dossier is not None
    assert canonical_dossier_bytes(omitted_result.dossier) == canonical_dossier_bytes(
        explicit_result.dossier
    )
    assert all(
        entry.authorship.authored_by is EvidenceAuthor.ACCOUNTABLE_PERSON
        and entry.authorship.attested_by_accountable_person
        for entry in omitted_result.dossier.evidence
    )


def test_unattested_assistant_observation_abstains_until_attested(tmp_path: Path) -> None:
    _write(tmp_path / "unattested", _version_two(attested=False))
    _write(tmp_path / "attested", _version_two(attested=True))

    unattested_result = validate_workspace(tmp_path / "unattested")
    attested_result = validate_workspace(tmp_path / "attested")
    assert unattested_result.dossier is not None and attested_result.dossier is not None

    unattested = evaluate_assessment(unattested_result.dossier)
    attested = evaluate_assessment(attested_result.dossier)

    assert unattested.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert attested.verdict is ArchitectureVerdict.SUPPORTED
    occurrences = [
        finding
        for finding in unattested.prerequisite_evaluation.findings
        if "decision-observed" in finding.evidence_ids and finding.rule_id.startswith("credible-")
    ]
    assert occurrences
    assert all("attest" in finding.remediation for finding in occurrences)
    assert all(finding.field.startswith("$.") for finding in occurrences)


def test_unattested_assistant_estimate_cannot_establish_a_decisive_fact(tmp_path: Path) -> None:
    verdicts: list[ArchitectureVerdict] = []
    for attested in (False, True):
        dossier = _version_two(attested=attested)
        evidence = dossier["evidence"]
        assert type(evidence) is list and type(evidence[0]) is dict
        entry = evidence[0]
        entry["kind"] = "estimate"
        entry["method"] = "Independently authored synthetic estimation method."
        entry.pop("provenance")
        entry.pop("observed_at")
        workspace = tmp_path / str(attested).lower()
        _write(workspace, dossier)
        validated = validate_workspace(workspace)
        assert validated.dossier is not None
        verdicts.append(evaluate_assessment(validated.dossier).verdict)

    assert verdicts == [
        ArchitectureVerdict.INSUFFICIENT_EVIDENCE,
        ArchitectureVerdict.SUPPORTED,
    ]


def test_assistant_assumptions_and_missing_entries_need_no_attestation(tmp_path: Path) -> None:
    dossier: dict[str, object] = {
        "schema_version": 2,
        "case": {"id": "uncertainty", "title": "Synthetic uncertainty"},
        "evidence": [
            {
                "id": "assumption",
                "kind": "assumption",
                "claim": "Synthetic assumption",
                "owner": "Reviewer",
                "affects": ["problem-value"],
                "falsified_by": "Synthetic observation",
                "authorship": {
                    "authored_by": "assistant",
                    "attested_by_accountable_person": False,
                },
            },
            {
                "id": "missing",
                "kind": "missing",
                "claim": "Synthetic gap",
                "owner": "Reviewer",
                "affects": ["comparative-fit"],
                "resolved_by": "Synthetic measurement",
                "authorship": {
                    "authored_by": "assistant",
                    "attested_by_accountable_person": False,
                },
            },
        ],
    }
    _write(tmp_path / "case", dossier)

    result = validate_workspace(tmp_path / "case")

    assert result.exit_code is ExitCode.SUCCESS
    assert result.dossier is not None
    assert tuple(entry.kind for entry in result.dossier.evidence) == (
        EvidenceKind.ASSUMPTION,
        EvidenceKind.MISSING,
    )


def test_attestation_change_is_an_explicit_reassessment_cause(tmp_path: Path) -> None:
    _write(tmp_path / "unattested", _version_two(attested=False))
    _write(tmp_path / "attested", _version_two(attested=True))
    old_dossier = validate_workspace(tmp_path / "unattested").dossier
    new_dossier = validate_workspace(tmp_path / "attested").dossier
    assert old_dossier is not None and new_dossier is not None
    old_record = compose_decision_record(old_dossier, tool_version="0.1.0")
    new_record = compose_decision_record(new_dossier, tool_version="0.1.0")
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_bytes(canonical_decision_record_bytes(old_record))
    new_path.write_bytes(canonical_decision_record_bytes(new_record))
    old = load_decision_record(old_path, root=tmp_path, role="old")
    new = load_decision_record(new_path, root=tmp_path, role="new")

    comparison = compare_decision_records(old, new)

    dossier = old["dossier"]
    assert type(dossier) is dict
    evidence = dossier["evidence"]
    assert type(evidence) is list
    assert all(type(entry) is dict and "authorship" in entry for entry in evidence)
    assert b"**Authorship**" in render_markdown_decision_report(old_record)
    assert comparison["changed_attestations"] == [
        {"evidence_id": "decision-observed", "new": True, "old": False}
    ]
    assert comparison["causes"]["attestation_evidence_ids"] == ["decision-observed"]
    assert comparison["context"]["attestation_evidence_ids"] == []
    assert comparison["verdict_delta"] == {
        "changed": True,
        "new": "supported",
        "old": "insufficient-evidence",
    }


def test_version_two_rejects_partial_or_unknown_authorship(tmp_path: Path) -> None:
    for index, authorship in enumerate(
        (
            {"authored_by": "assistant"},
            {
                "authored_by": "model",
                "attested_by_accountable_person": False,
            },
            {
                "authored_by": "assistant",
                "attested_by_accountable_person": "yes",
            },
            {
                "authored_by": "accountable-person",
                "attested_by_accountable_person": False,
            },
        )
    ):
        dossier = _version_two()
        evidence = dossier["evidence"]
        assert type(evidence) is list and type(evidence[0]) is dict
        evidence[0]["authorship"] = authorship
        workspace = tmp_path / str(index)
        _write(workspace, dossier)
        assert validate_workspace(workspace).exit_code is ExitCode.VALIDATION_FAILED
