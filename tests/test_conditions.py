from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
import yaml

from archsift.canonical import canonical_dossier_bytes, dossier_content_identity
from archsift.diagnostics import ExitCode
from archsift.validation import (
    ControlClass,
    DecisionArea,
    DecisionCondition,
    DecisionConditionStatus,
    validate_workspace,
)


def _case(*, conditions: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "case": {"id": "conditions", "title": "Synthetic conditions"},
        "evidence": [
            {
                "id": "comparison-observed",
                "kind": "observed",
                "claim": "A synthetic post-selection observation.",
                "owner": "Synthetic reviewer",
                "affects": ["comparative-fit"],
                "provenance": "evidence/synthetic-condition.txt",
                "observed_at": "2026-08-08",
            },
            {
                "id": "autonomy-observed",
                "kind": "observed",
                "claim": "A synthetic autonomy observation.",
                "owner": "Synthetic reviewer",
                "affects": ["autonomy-permission"],
                "provenance": "evidence/synthetic-autonomy.txt",
                "observed_at": "2026-08-08",
            },
        ],
        "decision_conditions": conditions if conditions is not None else [_condition()],
    }


def _condition(
    *,
    identifier: str = "verify-capacity",
    evidence_id: str = "comparison-observed",
) -> dict[str, object]:
    return {
        "id": identifier,
        "target_control_class": "fixed-ai-workflow",
        "decision_area": "comparative-fit",
        "statement": "Verify capacity before adoption.\x1b",
        "status": "unmet",
        "resolved_by": "Run the named capacity test.",
        "evidence_ids": [evidence_id],
    }


def _validate(tmp_path: Path, content: object):
    workspace = tmp_path / "case"
    workspace.mkdir()
    (workspace / "case.yaml").write_text(yaml.safe_dump(content, sort_keys=False))
    return validate_workspace(workspace)


def test_conditions_validate_to_immutable_authored_order_and_canonical_identity(
    tmp_path: Path,
) -> None:
    second = {
        **_condition(identifier="met-control"),
        "target_control_class": "human-owned-work",
        "decision_area": "autonomy-permission",
        "status": "met",
        "evidence_ids": ["autonomy-observed"],
    }
    result = _validate(tmp_path, _case(conditions=[_condition(), second]))

    assert result.exit_code is ExitCode.SUCCESS
    assert result.dossier is not None
    conditions = result.dossier.decision_conditions
    assert [condition.id for condition in conditions] == ["verify-capacity", "met-control"]
    assert conditions[0] == DecisionCondition(
        id="verify-capacity",
        target_control_class=ControlClass.FIXED_AI_WORKFLOW,
        decision_area=DecisionArea.COMPARATIVE_FIT,
        statement="Verify capacity before adoption.\x1b",
        status=DecisionConditionStatus.UNMET,
        resolved_by="Run the named capacity test.",
        evidence_ids=("comparison-observed",),
    )
    with pytest.raises(FrozenInstanceError):
        conditions[0].status = DecisionConditionStatus.MET  # type: ignore[misc]

    original_bytes = canonical_dossier_bytes(result.dossier)
    changed = replace(
        result.dossier,
        decision_conditions=(
            replace(conditions[0], resolved_by="Run a changed capacity test."),
            conditions[1],
        ),
    )
    assert canonical_dossier_bytes(result.dossier) == original_bytes
    assert canonical_dossier_bytes(changed) != original_bytes
    assert dossier_content_identity(changed) != dossier_content_identity(result.dossier)
    assert b"\\u001b" in original_bytes and b"\x1b" not in original_bytes


@pytest.mark.parametrize(
    ("conditions", "diagnostic_id", "field"),
    [
        (
            [_condition(), _condition()],
            "duplicate-decision-condition-id",
            "$.decision_conditions[1].id",
        ),
        (
            [_condition(evidence_id="absent")],
            "missing-decision-condition-evidence-reference",
            "$.decision_conditions[0].evidence_ids[0]",
        ),
        (
            [_condition(evidence_id="autonomy-observed")],
            "decision-condition-evidence-area-mismatch",
            "$.decision_conditions[0].evidence_ids[0]",
        ),
    ],
)
def test_condition_semantics_fail_closed_with_exact_fr010_diagnostics(
    tmp_path: Path,
    conditions: list[dict[str, object]],
    diagnostic_id: str,
    field: str,
) -> None:
    result = _validate(tmp_path, _case(conditions=conditions))

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert [(item.id, item.field, item.requirement) for item in result.diagnostics] == [
        (diagnostic_id, field, "FR-010")
    ]


@pytest.mark.parametrize(
    ("mutation", "field"),
    [
        ({"statement": "   "}, "$.decision_conditions[0].statement"),
        ({"status": "unknown"}, "$.decision_conditions[0].status"),
        ({"unexpected": "value"}, "$.decision_conditions[0].unexpected"),
    ],
)
def test_condition_schema_rejects_blank_unknown_and_unsupported_values(
    tmp_path: Path,
    mutation: dict[str, object],
    field: str,
) -> None:
    condition = {**_condition(), **mutation}
    result = _validate(tmp_path, _case(conditions=[condition]))

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].field == field
    assert result.diagnostics[0].requirement == "FR-010"
