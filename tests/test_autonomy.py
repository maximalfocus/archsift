from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from importlib.resources import files
from pathlib import Path
from typing import cast

import pytest
import yaml

from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.validation import (
    AutonomyAnswer,
    AutonomyPermission,
    AutonomyQuestion,
    ControlClass,
    HardVeto,
    HardVetoStatus,
    MandatoryHumanControl,
    evaluate_autonomy_permission_readiness,
    validate_workspace,
)
from archsift.workspace import initialize_workspace


def _workspace(tmp_path: Path) -> Path:
    target = tmp_path / "case"
    assert initialize_workspace(target).exit_code == ExitCode.SUCCESS
    return target


def _write_case(workspace: Path, content: object) -> None:
    (workspace / "case.yaml").write_text(yaml.safe_dump(content, sort_keys=False))


def _task() -> dict[str, object]:
    return {
        "operation": "Review one application and produce a disposition.",
        "starts_when": "A complete application enters the review queue.",
        "completes_when": "The disposition and rationale are recorded.",
        "accountable_owner": "Review operations lead",
        "actors": ["Case reviewer", "Quality approver"],
        "systems_and_tools": ["Application register"],
        "information_read": ["Submitted application"],
        "actions": [
            {
                "id": "draft-disposition",
                "description": "Draft a disposition and rationale.",
                "consequential": False,
                "approval_boundary": "A reviewer may draft without external release.",
            },
            {
                "id": "release-disposition",
                "description": "Release the approved disposition.",
                "consequential": True,
                "approval_boundary": "A quality approver must approve before release.",
            },
        ],
        "exclusions": ["Changing policy"],
    }


def _evidence(kind: str = "observed") -> dict[str, object]:
    entry: dict[str, object] = {
        "id": "autonomy-evidence",
        "kind": kind,
        "claim": "A sanitised autonomy-boundary claim.",
        "owner": "Risk reviewer",
        "affects": ["autonomy-permission"],
    }
    entry.update(
        {
            "observed": {
                "provenance": "evidence/sanitised-control-review.txt",
                "observed_at": "2026-08-07",
            },
            "estimate": {"method": "Estimate from a sanitised control review."},
            "assumption": {"falsified_by": "A control test disproves the claim."},
            "missing": {"resolved_by": "Perform a representative control test."},
        }[kind]
    )
    return entry


def _question(answer: str = "yes") -> dict[str, object]:
    return {
        "answer": answer,
        "rationale": "A sanitised evidence-backed autonomy fact.",
        "evidence_ids": ["autonomy-evidence"],
    }


def _autonomy(veto_status: str = "active") -> dict[str, object]:
    return {
        "actions_reversible": _question("no"),
        "failure_blast_radius_bounded": _question("yes"),
        "regulatory_automation_permitted": _question("no"),
        "data_confidence_sufficient": _question("yes"),
        "accountable_owner_assigned": _question("yes"),
        "decision_path_auditable": _question("yes"),
        "timely_human_intervention_available": _question("yes"),
        "safe_degradation_available": _question("yes"),
        "hard_vetoes": [
            {
                "id": "no-autonomous-release",
                "status": veto_status,
                "condition": "A disposition would be released without approval.",
                "consequence": "Autonomous release is prohibited.",
                "action_ids": ["release-disposition"],
                "evidence_ids": ["autonomy-evidence"],
            }
        ],
        "mandatory_human_controls": [
            {
                "id": "approve-release",
                "description": "Approve the disposition before external release.",
                "control_point": "Immediately before release.",
                "responsible_role": "Quality approver",
                "action_ids": ["release-disposition"],
                "evidence_ids": ["autonomy-evidence"],
            }
        ],
    }


def _dossier(
    *, autonomy: dict[str, object] | None = None, evidence_kind: str = "observed"
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "case": {"id": "x", "title": "X"},
        "task": _task(),
        "evidence": [_evidence(evidence_kind)],
        "autonomy_permission": autonomy if autonomy is not None else _autonomy(),
    }


@pytest.mark.parametrize("value", [None, [], "autonomy", 42])
def test_autonomy_permission_must_be_an_object(tmp_path: Path, value: object) -> None:
    workspace = _workspace(tmp_path)
    dossier = _dossier()
    dossier["autonomy_permission"] = value
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-007"


def test_raw_unquoted_yes_no_answers_remain_strings(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    content = yaml.safe_dump(_dossier(), sort_keys=False)
    content = content.replace("answer: 'yes'", "answer: yes").replace("answer: 'no'", "answer: no")
    (workspace / "case.yaml").write_text(content)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    facts = result.dossier.autonomy_permission
    assert facts is not None
    assert facts.actions_reversible.answer is AutonomyAnswer.NO
    assert facts.failure_blast_radius_bounded.answer is AutonomyAnswer.YES


def test_complete_autonomy_is_typed_immutable_ordered_and_ready(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    autonomy = _autonomy()
    vetoes = cast(list[dict[str, object]], autonomy["hard_vetoes"])
    vetoes[0]["prohibited_control_classes"] = ["fixed-ai-workflow", "agentic-control"]
    vetoes.append(
        {
            "id": "no-bulk-release",
            "status": "inactive",
            "condition": "Multiple dispositions would be released without review.",
            "consequence": "Bulk autonomous release is prohibited.",
            "action_ids": ["release-disposition"],
            "evidence_ids": ["autonomy-evidence"],
        }
    )
    _write_case(workspace, _dossier(autonomy=autonomy))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    facts = result.dossier.autonomy_permission
    assert isinstance(facts, AutonomyPermission)
    assert isinstance(facts.actions_reversible, AutonomyQuestion)
    assert [veto.id for veto in facts.hard_vetoes] == [
        "no-autonomous-release",
        "no-bulk-release",
    ]
    assert all(isinstance(veto, HardVeto) for veto in facts.hard_vetoes)
    assert facts.hard_vetoes[0].status is HardVetoStatus.ACTIVE
    assert facts.hard_vetoes[0].prohibited_control_classes == (
        ControlClass.FIXED_AI_WORKFLOW,
        ControlClass.AGENTIC_CONTROL,
    )
    assert facts.hard_vetoes[1].prohibited_control_classes is None
    assert all(
        isinstance(control, MandatoryHumanControl) for control in facts.mandatory_human_controls
    )
    assert evaluate_autonomy_permission_readiness(result.dossier).ready is True
    with pytest.raises(FrozenInstanceError):
        facts.hard_vetoes[0].condition = "Changed"  # type: ignore[misc]


def test_absent_autonomy_is_valid_but_not_ready(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_autonomy_permission_readiness(result.dossier)
    assert readiness.ready is False
    assert [finding.id for finding in readiness.findings] == ["autonomy-permission-missing"]
    assert readiness.findings[0].field == "$.autonomy_permission"


@pytest.mark.parametrize(
    "missing_field",
    [
        "actions_reversible",
        "failure_blast_radius_bounded",
        "regulatory_automation_permitted",
        "data_confidence_sufficient",
        "accountable_owner_assigned",
        "decision_path_auditable",
        "timely_human_intervention_available",
        "safe_degradation_available",
        "hard_vetoes",
        "mandatory_human_controls",
    ],
)
def test_every_autonomy_field_is_required(tmp_path: Path, missing_field: str) -> None:
    workspace = _workspace(tmp_path)
    autonomy = _autonomy()
    del autonomy[missing_field]
    _write_case(workspace, _dossier(autonomy=autonomy))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-007"
    assert missing_field in result.diagnostics[0].remediation


@pytest.mark.parametrize("missing_field", ["answer", "rationale", "evidence_ids"])
def test_every_question_field_is_required(tmp_path: Path, missing_field: str) -> None:
    workspace = _workspace(tmp_path)
    autonomy = _autonomy()
    question = cast(dict[str, object], autonomy["actions_reversible"])
    del question[missing_field]
    _write_case(workspace, _dossier(autonomy=autonomy))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-007"
    assert missing_field in result.diagnostics[0].remediation


@pytest.mark.parametrize(
    "missing_field", ["id", "status", "condition", "consequence", "action_ids", "evidence_ids"]
)
def test_every_hard_veto_field_is_required(tmp_path: Path, missing_field: str) -> None:
    workspace = _workspace(tmp_path)
    autonomy = _autonomy()
    veto = cast(list[dict[str, object]], autonomy["hard_vetoes"])[0]
    del veto[missing_field]
    _write_case(workspace, _dossier(autonomy=autonomy))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-007"
    assert missing_field in result.diagnostics[0].remediation


@pytest.mark.parametrize(
    "missing_field",
    ["id", "description", "control_point", "responsible_role", "action_ids", "evidence_ids"],
)
def test_every_human_control_field_is_required(tmp_path: Path, missing_field: str) -> None:
    workspace = _workspace(tmp_path)
    autonomy = _autonomy()
    control = cast(list[dict[str, object]], autonomy["mandatory_human_controls"])[0]
    del control[missing_field]
    _write_case(workspace, _dossier(autonomy=autonomy))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-007"
    assert missing_field in result.diagnostics[0].remediation


@pytest.mark.parametrize(
    ("record_name", "field", "value"),
    [
        ("question", "answer", "maybe"),
        ("question", "rationale", " \t "),
        ("question", "evidence_ids", [" \t "]),
        ("veto", "status", "maybe"),
        ("veto", "id", " \t "),
        ("veto", "condition", " \t "),
        ("veto", "consequence", " \t "),
        ("veto", "action_ids", [" \t "]),
        ("veto", "evidence_ids", [" \t "]),
        ("veto", "prohibited_control_classes", None),
        ("veto", "prohibited_control_classes", []),
        ("veto", "prohibited_control_classes", ["unsupported"]),
        (
            "veto",
            "prohibited_control_classes",
            ["agentic-control", "agentic-control"],
        ),
        ("control", "id", " \t "),
        ("control", "description", " \t "),
        ("control", "control_point", " \t "),
        ("control", "responsible_role", " \t "),
        ("control", "action_ids", [" \t "]),
        ("control", "evidence_ids", [" \t "]),
        ("veto", "action_ids", ["release-disposition", "release-disposition"]),
        ("control", "evidence_ids", ["autonomy-evidence", "autonomy-evidence"]),
    ],
)
def test_autonomy_values_fail_closed(
    tmp_path: Path, record_name: str, field: str, value: object
) -> None:
    workspace = _workspace(tmp_path)
    autonomy = _autonomy()
    records = {
        "question": cast(dict[str, object], autonomy["actions_reversible"]),
        "veto": cast(list[dict[str, object]], autonomy["hard_vetoes"])[0],
        "control": cast(list[dict[str, object]], autonomy["mandatory_human_controls"])[0],
    }
    records[record_name][field] = value
    _write_case(workspace, _dossier(autonomy=autonomy))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-007"
    assert result.diagnostics[0].remediation


def test_proxy_and_unknown_nested_fields_fail_closed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    autonomy = _autonomy()
    autonomy["autonomy_permitted"] = True
    autonomy["risk_score"] = 1
    cast(dict[str, object], autonomy["actions_reversible"])["safe_to_automate"] = True
    cast(list[dict[str, object]], autonomy["hard_vetoes"])[0]["weighted_value"] = 0
    cast(list[dict[str, object]], autonomy["mandatory_human_controls"])[0]["override"] = True
    _write_case(workspace, _dossier(autonomy=autonomy))

    result = validate_workspace(workspace)

    assert all(item.requirement == "FR-007" for item in result.diagnostics)
    assert {item.id for item in result.diagnostics} == {"unknown-field"}
    assert {item.field for item in result.diagnostics} == {
        "$.autonomy_permission.actions_reversible.safe_to_automate",
        "$.autonomy_permission.autonomy_permitted",
        "$.autonomy_permission.hard_vetoes[0].weighted_value",
        "$.autonomy_permission.mandatory_human_controls[0].override",
        "$.autonomy_permission.risk_score",
    }


def test_duplicate_boundary_ids_name_first_and_every_later_entry(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    autonomy = _autonomy()
    vetoes = cast(list[dict[str, object]], autonomy["hard_vetoes"])
    vetoes.extend([dict(vetoes[0]), dict(vetoes[0])])
    controls = cast(list[dict[str, object]], autonomy["mandatory_human_controls"])
    controls.append(dict(controls[0]))
    _write_case(workspace, _dossier(autonomy=autonomy))

    result = validate_workspace(workspace)

    assert [(item.id, item.field) for item in result.diagnostics] == [
        ("duplicate-hard-veto-id", "$.autonomy_permission.hard_vetoes[1].id"),
        ("duplicate-hard-veto-id", "$.autonomy_permission.hard_vetoes[2].id"),
        (
            "duplicate-human-control-id",
            "$.autonomy_permission.mandatory_human_controls[1].id",
        ),
    ]
    assert "hard_vetoes[0].id" in result.diagnostics[0].message
    assert "mandatory_human_controls[0].id" in result.diagnostics[2].message


@pytest.mark.parametrize(
    ("target", "expected_path"),
    [
        ("question", "$.autonomy_permission.actions_reversible.evidence_ids[0]"),
        ("veto", "$.autonomy_permission.hard_vetoes[0].evidence_ids[0]"),
        ("control", "$.autonomy_permission.mandatory_human_controls[0].evidence_ids[0]"),
    ],
)
def test_missing_evidence_references_are_exact(
    tmp_path: Path, target: str, expected_path: str
) -> None:
    workspace = _workspace(tmp_path)
    autonomy = _autonomy()
    if target == "question":
        cast(dict[str, object], autonomy["actions_reversible"])["evidence_ids"] = ["absent"]
    elif target == "veto":
        cast(list[dict[str, object]], autonomy["hard_vetoes"])[0]["evidence_ids"] = ["absent"]
    else:
        cast(list[dict[str, object]], autonomy["mandatory_human_controls"])[0]["evidence_ids"] = [
            "absent"
        ]
    _write_case(workspace, _dossier(autonomy=autonomy))

    result = validate_workspace(workspace)

    matches = [
        item for item in result.diagnostics if item.id == "missing-autonomy-evidence-reference"
    ]
    assert len(matches) == 1
    assert matches[0].field == expected_path
    assert matches[0].requirement == "FR-007"


def test_evidence_must_be_classified_for_autonomy(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    dossier = _dossier()
    cast(list[dict[str, object]], dossier["evidence"])[0]["affects"] = ["comparative-fit"]
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    mismatches = [
        item for item in result.diagnostics if item.id == "autonomy-evidence-area-mismatch"
    ]
    assert len(mismatches) == 10
    assert all(item.requirement == "FR-007" for item in mismatches)
    assert mismatches[0].field == "$.autonomy_permission.accountable_owner_assigned.evidence_ids[0]"
    assert (
        mismatches[-1].field
        == "$.autonomy_permission.timely_human_intervention_available.evidence_ids[0]"
    )


@pytest.mark.parametrize("collection", ["hard_vetoes", "mandatory_human_controls"])
def test_task_action_references_are_exact(tmp_path: Path, collection: str) -> None:
    workspace = _workspace(tmp_path)
    autonomy = _autonomy()
    cast(list[dict[str, object]], autonomy[collection])[0]["action_ids"] = ["absent"]
    _write_case(workspace, _dossier(autonomy=autonomy))

    result = validate_workspace(workspace)

    matches = [
        item for item in result.diagnostics if item.id == "missing-autonomy-task-action-reference"
    ]
    assert len(matches) == 1
    assert matches[0].field == f"$.autonomy_permission.{collection}[0].action_ids[0]"
    assert matches[0].requirement == "FR-007"


def test_boundary_action_references_require_a_task(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    dossier = _dossier()
    del dossier["task"]
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    matches = [
        item for item in result.diagnostics if item.id == "missing-autonomy-task-action-reference"
    ]
    assert [item.field for item in matches] == [
        "$.autonomy_permission.hard_vetoes[0].action_ids[0]",
        "$.autonomy_permission.mandatory_human_controls[0].action_ids[0]",
    ]


@pytest.mark.parametrize(
    ("kind", "ready"),
    [("observed", True), ("estimate", True), ("assumption", False), ("missing", False)],
)
def test_evidence_kind_controls_readiness(tmp_path: Path, kind: str, ready: bool) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier(evidence_kind=kind))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_autonomy_permission_readiness(result.dossier)
    assert readiness.ready is ready
    if ready:
        assert readiness.findings == ()
    else:
        assert len(readiness.findings) == 10
        assert all("credible" in finding.id for finding in readiness.findings)


@pytest.mark.parametrize(
    ("kind", "metadata_field"),
    [("observed", "provenance"), ("estimate", "method")],
)
def test_blank_credibility_metadata_cannot_make_readiness_true(
    tmp_path: Path, kind: str, metadata_field: str
) -> None:
    workspace = _workspace(tmp_path)
    dossier = _dossier(evidence_kind=kind)
    cast(list[dict[str, object]], dossier["evidence"])[0][metadata_field] = " \t "
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert evaluate_autonomy_permission_readiness(result.dossier).ready is False


def test_known_adverse_answers_and_active_veto_are_ready_facts(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier(autonomy=_autonomy("active")))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert evaluate_autonomy_permission_readiness(result.dossier).ready is True


def test_unknown_question_and_veto_produce_ordered_findings(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    autonomy = _autonomy("unknown")
    cast(dict[str, object], autonomy["actions_reversible"])["answer"] = "unknown"
    _write_case(workspace, _dossier(autonomy=autonomy))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    first = evaluate_autonomy_permission_readiness(result.dossier)
    assert first == evaluate_autonomy_permission_readiness(result.dossier)
    assert [(item.id, item.field) for item in first.findings] == [
        ("autonomy-answer-unknown", "$.autonomy_permission.actions_reversible.answer"),
        ("hard-veto-status-unknown", "$.autonomy_permission.hard_vetoes[0].status"),
    ]


def test_text_is_inert_and_does_not_open_named_paths(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "does-not-exist" / "control.txt"
    autonomy = _autonomy()
    cast(dict[str, object], autonomy["actions_reversible"])["rationale"] = str(outside)
    cast(list[dict[str, object]], autonomy["hard_vetoes"])[0]["condition"] = str(outside)
    cast(list[dict[str, object]], autonomy["mandatory_human_controls"])[0]["control_point"] = str(
        outside
    )
    _write_case(workspace, _dossier(autonomy=autonomy))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert not outside.exists()


def test_unknown_autonomy_field_cannot_emit_terminal_controls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    autonomy = _autonomy()
    autonomy["unsafe\x1b[31m\u202e"] = True
    _write_case(workspace, _dossier(autonomy=autonomy))

    assert main(["validate", str(workspace)]) == ExitCode.VALIDATION_FAILED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "\x1b" not in captured.err
    assert "\u202e" not in captured.err
    assert "\\x1b[31m\\u202e" in captured.err


def test_json_reports_readiness_without_permission_conclusion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier())

    assert main(["validate", str(workspace), "--json"]) == ExitCode.SUCCESS
    payload = json.loads(capsys.readouterr().out)
    assert payload["autonomy_permission_defined"] is True
    assert payload["autonomy_permission_ready"] is True
    assert payload["hard_veto_count"] == 1
    assert payload["mandatory_human_control_count"] == 1
    assert "autonomy_permitted" not in payload
    assert "risk_score" not in payload
    assert "verdict" not in payload


def test_template_example_is_valid_and_ready(tmp_path: Path) -> None:
    guidance = (
        files("archsift").joinpath("templates/workspace-README.md").read_text(encoding="utf-8")
    )
    blocks = guidance.split("```yaml")
    task_example = yaml.safe_load(blocks[1].split("```", 1)[0])
    evidence_example = yaml.safe_load(blocks[2].split("```", 1)[0])
    autonomy_example = yaml.safe_load(blocks[5].split("```", 1)[0])
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "task": task_example["task"],
            "evidence": evidence_example["evidence"],
            "autonomy_permission": autonomy_example["autonomy_permission"],
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert evaluate_autonomy_permission_readiness(result.dossier).ready is True
