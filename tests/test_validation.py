from __future__ import annotations

import json
import os
from dataclasses import FrozenInstanceError
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import cast

import pytest
import yaml
from jsonschema import Draft202012Validator

from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.validation import (
    AgencyAnswer,
    AgencyNecessity,
    AgencyQuestion,
    AssumptionEvidence,
    DecisionArea,
    EstimateEvidence,
    EvidenceKind,
    MissingEvidence,
    ObservedEvidence,
    ProblemBaseline,
    ProblemConstraint,
    ProblemOutcome,
    ProblemValue,
    ResidualCase,
    TaskAction,
    TaskBoundary,
    evaluate_agency_necessity_readiness,
    evaluate_problem_value_readiness,
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
        "operation": "Review one submitted application and produce a disposition.",
        "starts_when": "A complete application enters the review queue.",
        "completes_when": "The disposition and rationale are recorded.",
        "accountable_owner": "Review operations lead",
        "actors": ["Case reviewer", "Quality approver"],
        "systems_and_tools": ["Application register", "Policy search"],
        "information_read": ["Submitted application", "Current policy"],
        "actions": [
            {
                "id": "draft-disposition",
                "description": "Draft a disposition and rationale.",
                "consequential": False,
                "approval_boundary": "A reviewer may draft; no external release occurs.",
            },
            {
                "id": "release-disposition",
                "description": "Release the approved disposition.",
                "consequential": True,
                "approval_boundary": "A quality approver must approve before release.",
            },
        ],
        "exclusions": ["Changing policy", "Executing downstream enforcement"],
    }


def _agency_question(
    answer: str = "yes", evidence_id: str = "agency-observed"
) -> dict[str, object]:
    return {
        "answer": answer,
        "rationale": "A sanitised evidence-backed agency fact.",
        "evidence_ids": [evidence_id],
    }


def _agency_necessity(fixed_workflow_answer: str = "no") -> dict[str, object]:
    residual_cases: list[dict[str, object]] = []
    if fixed_workflow_answer != "yes":
        residual_cases.append(
            {
                "id": "evidence-dependent-follow-up",
                "description": "An unanticipated evidence gap changes the next check.",
                "fixed_workflow_failure": "The next approved retrieval step is not predefined.",
                "evidence_ids": ["agency-observed"],
            }
        )
    return {
        "execution_steps_predefinable": _agency_question("no"),
        "step_count_or_order_predictable": _agency_question("no"),
        "runtime_tool_choice_required": _agency_question("yes"),
        "runtime_replanning_required": _agency_question("yes"),
        "environmental_feedback_available": _agency_question("yes"),
        "completion_independently_verifiable": _agency_question("yes"),
        "effects_independently_verifiable": _agency_question("yes"),
        "fixed_workflow_sufficient": _agency_question(fixed_workflow_answer),
        "residual_cases": residual_cases,
    }


def _agency_evidence(
    kind: str = "observed", identifier: str = "agency-observed"
) -> dict[str, object]:
    entry = _entry(kind, identifier)
    entry["affects"] = ["agency-necessity"]
    return entry


def _problem_value() -> dict[str, object]:
    return {
        "outcomes": [
            {
                "id": "reduce-time",
                "description": "Reduce handling time.",
                "measure": "Median minutes per case",
                "target": "At most 8 minutes",
                "baseline_id": "current-time",
                "binding": True,
                "evidence_ids": ["baseline-observed"],
            },
            {
                "id": "compare-capacity",
                "description": "Compare candidate capacity.",
                "measure": "Completed cases per month",
                "target": "Report the measured value",
                "baseline_id": "current-volume",
                "binding": False,
                "evidence_ids": ["volume-assumption"],
            },
        ],
        "baselines": [
            {
                "id": "current-time",
                "description": "Current handling time.",
                "measure": "Median minutes per case",
                "value": "12 minutes",
                "evidence_ids": ["baseline-observed"],
            },
            {
                "id": "current-volume",
                "description": "Expected monthly volume.",
                "measure": "Completed cases per month",
                "value": "About 1000",
                "evidence_ids": ["volume-assumption"],
            },
        ],
        "constraints": [
            {
                "id": "capacity-view",
                "description": "Show capacity for comparison.",
                "test": "Completed cases per month is reported",
                "required_result": "A value is reported; no minimum",
                "binding": False,
                "evidence_ids": ["volume-assumption"],
            }
        ],
        "affected_volume": {
            "statement": "The task handles material monthly volume.",
            "evidence_ids": ["volume-assumption"],
        },
        "material_pain": {
            "statement": "Manual retrieval adds handling time.",
            "evidence_ids": ["baseline-observed"],
        },
        "error_cost": {
            "statement": "Incorrect output requires rework.",
            "evidence_ids": ["baseline-observed"],
        },
        "technology_limitation": {
            "statement": "Current search may contribute to delay.",
            "evidence_ids": ["volume-assumption"],
        },
    }


def _problem_evidence() -> list[dict[str, object]]:
    return [
        _entry("observed", "baseline-observed"),
        _entry("assumption", "volume-assumption"),
    ]


def _entry(kind: str, identifier: str = "evidence-1") -> dict[str, object]:
    entry: dict[str, object] = {
        "id": identifier,
        "kind": kind,
        "claim": f"A sanitised {kind} claim.",
        "owner": "Architecture reviewer",
        "affects": ["problem-value"],
    }
    entry.update(
        {
            "observed": {"provenance": "evidence/sample.txt", "observed_at": "2026-08-06"},
            "assumption": {"falsified_by": "A representative measurement disproves it."},
            "estimate": {"method": "Estimate from a sanitised sample."},
            "missing": {"resolved_by": "Collect a representative measurement."},
        }[kind]
    )
    return entry


def test_packaged_schema_is_available() -> None:
    schema = files("archsift").joinpath("schemas/dossier-v1.schema.json")
    payload = json.loads(schema.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(payload)
    assert payload["properties"]["schema_version"]["const"] == 1
    assert payload["additionalProperties"] is False
    assert payload["properties"]["case"]["additionalProperties"] is False
    assert payload["properties"]["evidence"]["type"] == "array"
    assert payload["properties"]["task"]["$ref"] == "#/$defs/taskBoundary"
    assert payload["properties"]["problem_value"]["$ref"] == "#/$defs/problemValue"
    assert payload["properties"]["agency_necessity"]["$ref"] == "#/$defs/agencyNecessity"
    assert payload["properties"]["autonomy_permission"]["$ref"] == "#/$defs/autonomyPermission"
    assert payload["$defs"]["evidenceEntry"]["additionalProperties"] is False
    assert payload["$defs"]["taskBoundary"]["additionalProperties"] is False
    assert payload["$defs"]["taskAction"]["additionalProperties"] is False
    assert payload["$defs"]["problemValue"]["additionalProperties"] is False
    assert payload["$defs"]["problemOutcome"]["additionalProperties"] is False
    assert payload["$defs"]["problemBaseline"]["additionalProperties"] is False
    assert payload["$defs"]["problemConstraint"]["additionalProperties"] is False
    assert payload["$defs"]["agencyNecessity"]["additionalProperties"] is False
    assert payload["$defs"]["agencyQuestion"]["additionalProperties"] is False
    assert payload["$defs"]["residualCase"]["additionalProperties"] is False
    assert payload["$defs"]["autonomyPermission"]["additionalProperties"] is False
    assert payload["$defs"]["autonomyQuestion"]["additionalProperties"] is False
    assert payload["$defs"]["hardVeto"]["additionalProperties"] is False
    assert payload["$defs"]["mandatoryHumanControl"]["additionalProperties"] is False


def test_generated_workspace_validates(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.diagnostics == ()
    assert result.dossier is not None
    assert result.dossier.schema_version == 1
    assert result.dossier.case.id == "case"
    assert result.dossier.evidence == ()
    assert result.dossier.task is None
    assert result.dossier.agency_necessity is None
    assert result.dossier.autonomy_permission is None


def test_minimal_version_one_dossier_remains_valid(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, {"schema_version": 1, "case": {"id": "x", "title": "X"}})

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.evidence == ()
    assert result.dossier.task is None
    assert result.dossier.agency_necessity is None
    assert result.dossier.autonomy_permission is None


@pytest.mark.parametrize("kind", ["observed", "assumption", "estimate", "missing"])
def test_each_evidence_kind_validates_and_is_typed(tmp_path: Path, kind: str) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_entry(kind)],
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    evidence = result.dossier.evidence[0]
    expected_types = {
        "observed": ObservedEvidence,
        "assumption": AssumptionEvidence,
        "estimate": EstimateEvidence,
        "missing": MissingEvidence,
    }
    assert isinstance(evidence, expected_types[kind])
    assert evidence.kind is EvidenceKind(kind)
    assert evidence.affects == (DecisionArea.PROBLEM_VALUE,)
    if isinstance(evidence, ObservedEvidence):
        assert evidence.observed_at == date(2026, 8, 6)


def test_evidence_author_order_and_affects_order_are_preserved(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    first = _entry("estimate", "first")
    first["affects"] = ["comparative-fit", "agency-necessity"]
    second = _entry("missing", "second")
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [first, second],
        },
    )

    result = validate_workspace(workspace)

    assert result.dossier is not None
    assert [entry.id for entry in result.dossier.evidence] == ["first", "second"]
    assert result.dossier.evidence[0].affects == (
        DecisionArea.COMPARATIVE_FIT,
        DecisionArea.AGENCY_NECESSITY,
    )


def test_complete_task_boundary_validates_as_immutable_typed_objects(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    task = _task()
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "task": task,
            "evidence": [],
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    boundary = result.dossier.task
    assert isinstance(boundary, TaskBoundary)
    assert boundary.operation == task["operation"]
    assert boundary.actors == ("Case reviewer", "Quality approver")
    assert boundary.systems_and_tools == ("Application register", "Policy search")
    assert boundary.information_read == ("Submitted application", "Current policy")
    assert [action.id for action in boundary.actions] == [
        "draft-disposition",
        "release-disposition",
    ]
    assert all(isinstance(action, TaskAction) for action in boundary.actions)
    assert boundary.exclusions == ("Changing policy", "Executing downstream enforcement")
    with pytest.raises(FrozenInstanceError):
        boundary.operation = "Changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        boundary.actions[0].description = "Changed"  # type: ignore[misc]


def test_explicit_empty_systems_and_information_are_valid(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    task = _task()
    task["systems_and_tools"] = []
    task["information_read"] = []
    _write_case(
        workspace,
        {"schema_version": 1, "case": {"id": "x", "title": "X"}, "task": task},
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.task is not None
    assert result.dossier.task.systems_and_tools == ()
    assert result.dossier.task.information_read == ()


def test_broad_programme_label_alone_is_not_a_task_boundary(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "task": {"operation": "Modernise review"},
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert len(result.diagnostics) == 8
    assert all(diagnostic.field == "$.task" for diagnostic in result.diagnostics)
    assert all(diagnostic.requirement == "FR-003" for diagnostic in result.diagnostics)
    assert all(
        diagnostic.remediation.startswith("Add the required field")
        for diagnostic in result.diagnostics
    )


@pytest.mark.parametrize(
    "missing_field",
    [
        "operation",
        "starts_when",
        "completes_when",
        "accountable_owner",
        "actors",
        "systems_and_tools",
        "information_read",
        "actions",
        "exclusions",
    ],
)
def test_every_task_boundary_field_is_required(tmp_path: Path, missing_field: str) -> None:
    workspace = _workspace(tmp_path)
    task = _task()
    del task[missing_field]
    _write_case(
        workspace,
        {"schema_version": 1, "case": {"id": "x", "title": "X"}, "task": task},
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].field == "$.task"
    assert result.diagnostics[0].requirement == "FR-003"
    assert missing_field in result.diagnostics[0].remediation


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operation", ""),
        ("starts_when", ""),
        ("completes_when", ""),
        ("accountable_owner", ""),
        ("actors", []),
        ("actors", ["Reviewer", "Reviewer"]),
        ("systems_and_tools", [""]),
        ("systems_and_tools", ["Register", "Register"]),
        ("information_read", [""]),
        ("information_read", ["Policy", "Policy"]),
        ("actions", []),
        ("exclusions", []),
        ("exclusions", ["Policy change", "Policy change"]),
    ],
)
def test_task_boundary_values_fail_closed(tmp_path: Path, field: str, value: object) -> None:
    workspace = _workspace(tmp_path)
    task = _task()
    task[field] = value
    _write_case(
        workspace,
        {"schema_version": 1, "case": {"id": "x", "title": "X"}, "task": task},
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics
    assert all(diagnostic.requirement == "FR-003" for diagnostic in result.diagnostics)
    assert all(diagnostic.remediation for diagnostic in result.diagnostics)


@pytest.mark.parametrize(
    "field",
    [
        "operation",
        "starts_when",
        "completes_when",
        "accountable_owner",
        "actors",
        "systems_and_tools",
        "information_read",
        "exclusions",
        "action.id",
        "action.description",
        "action.approval_boundary",
    ],
)
def test_task_strings_require_non_whitespace_content(tmp_path: Path, field: str) -> None:
    workspace = _workspace(tmp_path)
    task = _task()
    if field.startswith("action."):
        actions = cast(list[dict[str, object]], task["actions"])
        actions[0][field.removeprefix("action.")] = " \t "
    elif field in {"actors", "systems_and_tools", "information_read", "exclusions"}:
        task[field] = [" \t "]
    else:
        task[field] = " \t "
    _write_case(
        workspace,
        {"schema_version": 1, "case": {"id": "x", "title": "X"}, "task": task},
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-003"
    assert "non-whitespace" in result.diagnostics[0].remediation


@pytest.mark.parametrize(
    "missing_field",
    ["id", "description", "consequential", "approval_boundary"],
)
def test_every_task_action_field_is_required(tmp_path: Path, missing_field: str) -> None:
    workspace = _workspace(tmp_path)
    task = _task()
    actions = cast(list[dict[str, object]], task["actions"])
    del actions[0][missing_field]
    _write_case(
        workspace,
        {"schema_version": 1, "case": {"id": "x", "title": "X"}, "task": task},
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    diagnostic = result.diagnostics[0]
    assert diagnostic.field == "$.task.actions[0]"
    assert diagnostic.requirement == "FR-003"
    assert missing_field in diagnostic.remediation


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ""),
        ("description", ""),
        ("consequential", "yes"),
        ("approval_boundary", ""),
    ],
)
def test_task_action_contract_fails_closed(tmp_path: Path, field: str, value: object) -> None:
    workspace = _workspace(tmp_path)
    task = _task()
    actions = cast(list[dict[str, object]], task["actions"])
    actions[0][field] = value
    _write_case(
        workspace,
        {"schema_version": 1, "case": {"id": "x", "title": "X"}, "task": task},
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].field.startswith("$.task.actions[0].")
    assert result.diagnostics[0].requirement == "FR-003"


def test_unknown_task_and_action_fields_fail_with_fr003(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    task = _task()
    task["unknown_task"] = True
    actions = cast(list[dict[str, object]], task["actions"])
    actions[0]["unknown_action"] = True
    _write_case(
        workspace,
        {"schema_version": 1, "case": {"id": "x", "title": "X"}, "task": task},
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert [
        (diagnostic.id, diagnostic.field, diagnostic.requirement)
        for diagnostic in result.diagnostics
    ] == [
        ("unknown-field", "$.task.unknown_task", "FR-003"),
        ("unknown-field", "$.task.actions[0].unknown_action", "FR-003"),
    ]


def test_duplicate_task_action_ids_identify_first_and_later_actions(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    task = _task()
    actions = cast(list[dict[str, object]], task["actions"])
    actions[1]["id"] = actions[0]["id"]
    _write_case(
        workspace,
        {"schema_version": 1, "case": {"id": "x", "title": "X"}, "task": task},
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert diagnostic.id == "duplicate-task-action-id"
    assert diagnostic.field == "$.task.actions[1].id"
    assert diagnostic.requirement == "FR-003"
    assert "$.task.actions[0].id" in diagnostic.message
    assert diagnostic.remediation


def test_duplicate_task_action_json_and_quiet_modes_are_stable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    task = _task()
    actions = cast(list[dict[str, object]], task["actions"])
    actions[1]["id"] = actions[0]["id"]
    _write_case(
        workspace,
        {"schema_version": 1, "case": {"id": "x", "title": "X"}, "task": task},
    )

    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    first = capsys.readouterr()
    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    second = capsys.readouterr()
    assert first == second
    payload = json.loads(first.out)
    assert payload["diagnostics"][0]["id"] == "duplicate-task-action-id"
    assert payload["diagnostics"][0]["requirement"] == "FR-003"

    assert main(["validate", str(workspace), "--quiet"]) == ExitCode.VALIDATION_FAILED
    quiet = capsys.readouterr()
    assert quiet.out == quiet.err == ""


def test_task_text_is_inert_and_does_not_open_named_paths(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    task = _task()
    outside = tmp_path / "does-not-exist" / "outside.txt"
    task["systems_and_tools"] = [str(outside)]
    task["information_read"] = [str(outside)]
    _write_case(
        workspace,
        {"schema_version": 1, "case": {"id": "x", "title": "X"}, "task": task},
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.task is not None
    assert result.dossier.task.systems_and_tools == (str(outside),)
    assert not outside.exists()


def _task_yaml(consequential: str) -> str:
    return f"""schema_version: 1
case: {{id: x, title: X}}
task:
  operation: Review one submitted application.
  starts_when: A complete application enters the queue.
  completes_when: The disposition is recorded.
  accountable_owner: Operations lead
  actors: [Reviewer]
  systems_and_tools: []
  information_read: [Submitted application]
  actions:
    - id: record-disposition
      description: Record the reviewed disposition.
      consequential: {consequential}
      approval_boundary: A human reviewer approves before recording.
  exclusions: [Changing policy]
"""


@pytest.mark.parametrize("value", ["yes", "Yes", "no", "No", "on", "On", "off", "Off"])
def test_yes_no_forms_are_not_silently_booleans(tmp_path: Path, value: str) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "case.yaml").write_text(_task_yaml(value))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].field == "$.task.actions[0].consequential"
    assert result.diagnostics[0].requirement == "FR-003"


@pytest.mark.parametrize("value", ["true", "True", "false", "False"])
def test_true_false_forms_remain_booleans(tmp_path: Path, value: str) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "case.yaml").write_text(_task_yaml(value))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.task is not None
    assert result.dossier.task.actions[0].consequential is (value in ("true", "True"))


def test_operation_only_task_remediation_names_every_missing_field(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "task": {"operation": "Modernise review"},
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert len(result.diagnostics) == 8
    missing = (
        "starts_when",
        "completes_when",
        "accountable_owner",
        "actors",
        "systems_and_tools",
        "information_read",
        "actions",
        "exclusions",
    )
    seen: set[str] = set()
    for diagnostic in result.diagnostics:
        assert diagnostic.requirement == "FR-003"
        named = [name for name in missing if f"$.task.{name}" in diagnostic.remediation]
        assert len(named) == 1
        seen.add(named[0])
    assert seen == set(missing)


def test_duplicate_action_ids_report_every_later_duplicate(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    task = _task()
    actions = cast(list[dict[str, object]], task["actions"])
    actions.append(dict(actions[0]))
    actions[1]["id"] = actions[0]["id"]
    actions[2]["id"] = actions[0]["id"]
    actions[2]["description"] = "A third occurrence."
    _write_case(
        workspace,
        {"schema_version": 1, "case": {"id": "x", "title": "X"}, "task": task},
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert [diagnostic.field for diagnostic in result.diagnostics] == [
        "$.task.actions[1].id",
        "$.task.actions[2].id",
    ]
    assert all(
        diagnostic.id == "duplicate-task-action-id" and "$.task.actions[0].id" in diagnostic.message
        for diagnostic in result.diagnostics
    )


@pytest.mark.parametrize("task", [None, [], "task", 42])
def test_task_must_be_an_object_when_supplied(tmp_path: Path, task: object) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {"schema_version": 1, "case": {"id": "x", "title": "X"}, "task": task},
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert all(diagnostic.requirement == "FR-003" for diagnostic in result.diagnostics)


def test_template_task_example_remains_a_valid_complete_boundary(tmp_path: Path) -> None:
    guidance = (
        files("archsift").joinpath("templates/workspace-README.md").read_text(encoding="utf-8")
    )
    blocks = guidance.split("```yaml")
    assert len(blocks) >= 2
    parsed = yaml.safe_load(blocks[1].split("```", 1)[0])
    assert isinstance(parsed, dict)
    assert isinstance(parsed["task"], dict)
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "task": parsed["task"],
            "evidence": [],
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.task is not None
    assert result.dossier.task.operation


def test_evidence_and_action_duplicates_report_in_stable_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    task = _task()
    actions = cast(list[dict[str, object]], task["actions"])
    actions[1]["id"] = actions[0]["id"]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_entry("observed", "dup"), _entry("estimate", "dup")],
            "task": task,
        },
    )

    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    first = capsys.readouterr().out
    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    second = capsys.readouterr().out
    assert first == second
    payload = json.loads(first)
    assert [item["id"] for item in payload["diagnostics"]] == [
        "duplicate-evidence-id",
        "duplicate-task-action-id",
    ]


def test_missing_workspace_fails_closed(tmp_path: Path) -> None:
    result = validate_workspace(tmp_path / "missing")

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    diagnostic = result.diagnostics[0]
    assert diagnostic.id == "workspace-missing"
    assert diagnostic.file == "case.yaml"
    assert diagnostic.field == "$"
    assert diagnostic.requirement == "FR-001"
    assert diagnostic.remediation


def test_missing_case_file_fails_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "case"
    workspace.mkdir()

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "case-file-missing"


@pytest.mark.skipif(os.name == "nt", reason="Windows CI may not permit unprivileged symlinks")
def test_case_file_symlink_escape_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "case"
    workspace.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("schema_version: 1\ncase: {id: x, title: x}\n")
    (workspace / "case.yaml").symlink_to(outside)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.UNSAFE_PATH
    assert result.diagnostics[0].id == "case-file-outside-workspace"
    assert result.diagnostics[0].requirement == "NFR-004"


@pytest.mark.parametrize("content", ["case: [\n", "\xff"])
def test_malformed_or_non_utf8_yaml_is_distinct(tmp_path: Path, content: str) -> None:
    workspace = _workspace(tmp_path)
    if content == "\xff":
        (workspace / "case.yaml").write_bytes(b"\xff")
    else:
        (workspace / "case.yaml").write_text(content)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "malformed-yaml"
    assert result.diagnostics[0].requirement == "FR-012"


def test_unsafe_yaml_constructor_is_rejected_without_execution(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    marker = tmp_path / "executed"
    payload = f"!!python/object/apply:pathlib.Path.touch ['{marker}']\n"
    (workspace / "case.yaml").write_text(payload)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "malformed-yaml"
    assert not marker.exists()


@pytest.mark.parametrize("content", [None, [], "text", 42])
def test_non_mapping_document_is_malformed(tmp_path: Path, content: object) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, content)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "dossier-not-mapping"


def test_missing_schema_version_is_structural_failure(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, {"case": {"id": "x", "title": "X"}})

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "schema-version-missing"
    assert result.diagnostics[0].field == "$.schema_version"


@pytest.mark.parametrize("version", [0, 2, "1", True, None])
def test_unsupported_schema_version_has_distinct_exit(tmp_path: Path, version: object) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, {"schema_version": version, "case": {"id": "x", "title": "X"}})

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.UNSUPPORTED_SCHEMA
    assert result.diagnostics[0].id == "schema-version-unsupported"


@pytest.mark.parametrize(
    "content",
    [
        # Non-string YAML keys (int, bool, null) mixed with string keys must
        # fail closed as unknown fields, not crash into an internal error.
        "schema_version: 1\ncase: {id: x, title: X}\nproblem_value: {1: a, extra: b}\n",
        "schema_version: 1\ncase: {id: x, title: X}\nproblem_value: {1: a, '1': b}\n",
        "schema_version: 1\ncase: {id: x, title: X}\ntrue: a\nextra: b\n",
        "schema_version: 1\ncase: {id: x, title: X, null: a, extra: b}\n",
    ],
)
def test_mixed_type_unknown_keys_fail_closed_without_internal_error(
    tmp_path: Path, content: str, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "case.yaml").write_text(content)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert any(diagnostic.id == "unknown-field" for diagnostic in result.diagnostics)
    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED


@pytest.mark.parametrize(
    ("document", "field"),
    [
        ({"schema_version": 1, "case": {"id": "x", "title": "X"}, "extra": 1}, "$.extra"),
        (
            {"schema_version": 1, "case": {"id": "x", "title": "X", "extra": 1}},
            "$.case.extra",
        ),
    ],
)
def test_unknown_fields_fail_closed(tmp_path: Path, document: object, field: str) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, document)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "unknown-field"
    assert result.diagnostics[0].field == field


@pytest.mark.parametrize(
    "case",
    [
        {},
        {"id": "x"},
        {"title": "X"},
        {"id": "", "title": "X"},
        {"id": "x", "title": ""},
        {"id": 1, "title": "X"},
        {"id": "x", "title": []},
    ],
)
def test_required_case_fields_are_validated(tmp_path: Path, case: object) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, {"schema_version": 1, "case": case})

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics
    for diagnostic in result.diagnostics:
        assert diagnostic.file == "case.yaml"
        assert diagnostic.field.startswith("$")
        assert diagnostic.requirement == "FR-002"
        assert diagnostic.remediation


@pytest.mark.parametrize(
    "entry",
    [
        {"kind": "observed", "claim": "x", "owner": "x", "affects": ["problem-value"]},
        {"id": "x", "kind": "observed", "claim": "x", "owner": "x", "affects": []},
        {
            "id": "x",
            "kind": "observed",
            "claim": "x",
            "owner": "x",
            "affects": ["problem-value", "problem-value"],
            "provenance": "sample",
            "observed_at": "2026-08-06",
        },
        {
            "id": "x",
            "kind": "observed",
            "claim": "x",
            "owner": "x",
            "affects": ["unknown-area"],
            "provenance": "sample",
            "observed_at": "2026-08-06",
        },
        {
            "id": "x",
            "kind": "unknown",
            "claim": "x",
            "owner": "x",
            "affects": ["problem-value"],
        },
    ],
)
def test_common_evidence_fields_fail_closed_with_fr004(
    tmp_path: Path, entry: dict[str, object]
) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [entry],
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics
    assert all(diagnostic.requirement == "FR-004" for diagnostic in result.diagnostics)
    assert all(diagnostic.remediation for diagnostic in result.diagnostics)


@pytest.mark.parametrize(
    ("kind", "required_field"),
    [
        ("observed", "provenance"),
        ("assumption", "falsified_by"),
        ("estimate", "method"),
        ("missing", "resolved_by"),
    ],
)
def test_evidence_kind_requires_its_metadata(
    tmp_path: Path, kind: str, required_field: str
) -> None:
    workspace = _workspace(tmp_path)
    entry = _entry(kind)
    del entry[required_field]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [entry],
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-004"
    assert required_field in result.diagnostics[0].remediation


def test_evidence_kind_rejects_irrelevant_metadata(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    entry = _entry("assumption")
    entry["method"] = "This belongs only to an estimate."
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [entry],
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-004"
    assert "do not apply" in result.diagnostics[0].remediation


def test_unquoted_yaml_observed_date_is_validated_as_a_schema_string(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "case.yaml").write_text(
        """schema_version: 1
case: {id: x, title: X}
evidence:
  - id: observation
    kind: observed
    claim: A sanitised observation.
    owner: Reviewer
    affects: [problem-value]
    provenance: evidence/sample.txt
    observed_at: 2026-08-06
"""
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    evidence = result.dossier.evidence[0]
    assert isinstance(evidence, ObservedEvidence)
    assert evidence.observed_at == date(2026, 8, 6)


@pytest.mark.parametrize("observed_at", ["2026-02-29", "2026-13-01", "06/08/2026"])
def test_observed_date_must_be_a_real_calendar_date(tmp_path: Path, observed_at: str) -> None:
    workspace = _workspace(tmp_path)
    entry = _entry("observed")
    entry["observed_at"] = observed_at
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [entry],
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    diagnostic = result.diagnostics[0]
    assert diagnostic.field == "$.evidence[0].observed_at"
    assert diagnostic.requirement == "FR-004"
    assert "YYYY-MM-DD" in diagnostic.remediation


def test_unknown_evidence_field_fails_with_fr004(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    entry = _entry("estimate")
    entry["unrecognised"] = True
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [entry],
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    diagnostic = result.diagnostics[0]
    assert diagnostic.id == "unknown-field"
    assert diagnostic.field == "$.evidence[0].unrecognised"
    assert diagnostic.requirement == "FR-004"


def test_duplicate_evidence_ids_identify_first_and_later_entries(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    first = _entry("observed", "same-id")
    second = _entry("estimate", "same-id")
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [first, second],
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert diagnostic.id == "duplicate-evidence-id"
    assert diagnostic.field == "$.evidence[1].id"
    assert diagnostic.requirement == "FR-004"
    assert "$.evidence[0].id" in diagnostic.message
    assert diagnostic.remediation


def test_duplicate_evidence_id_json_and_quiet_modes_are_stable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_entry("assumption", "same"), _entry("missing", "same")],
        },
    )

    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    first = capsys.readouterr()
    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    second = capsys.readouterr()
    assert first == second
    payload = json.loads(first.out)
    assert payload["diagnostics"][0]["id"] == "duplicate-evidence-id"
    assert payload["diagnostics"][0]["requirement"] == "FR-004"

    assert main(["validate", str(workspace), "--quiet"]) == ExitCode.VALIDATION_FAILED
    quiet = capsys.readouterr()
    assert quiet.out == quiet.err == ""


def test_provenance_is_inert_metadata_and_is_not_opened(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    entry = _entry("observed")
    entry["provenance"] = str(tmp_path / "does-not-exist" / "outside.txt")
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [entry],
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert isinstance(result.dossier.evidence[0], ObservedEvidence)
    assert result.dossier.evidence[0].provenance == entry["provenance"]


def test_validate_success_json_reports_evidence_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_entry("observed"), _entry("missing", "gap")],
        },
    )

    assert main(["validate", str(workspace), "--json"]) == ExitCode.SUCCESS
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "action_count": 0,
        "agency_necessity_defined": False,
        "agency_necessity_ready": False,
        "autonomy_permission_defined": False,
        "autonomy_permission_ready": False,
        "constraint_count": 0,
        "diagnostics": [],
        "evidence_count": 2,
        "exit_code": 0,
        "file": "case.yaml",
        "hard_veto_count": 0,
        "mandatory_human_control_count": 0,
        "outcome_count": 0,
        "problem_value_defined": False,
        "problem_value_ready": False,
        "residual_case_count": 0,
        "schema_version": 1,
        "status": "valid",
        "task_defined": False,
    }


def test_validate_success_json_reports_task_boundary_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "task": _task(),
        },
    )

    assert main(["validate", str(workspace), "--json"]) == ExitCode.SUCCESS
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "action_count": 2,
        "agency_necessity_defined": False,
        "agency_necessity_ready": False,
        "autonomy_permission_defined": False,
        "autonomy_permission_ready": False,
        "constraint_count": 0,
        "diagnostics": [],
        "evidence_count": 0,
        "exit_code": 0,
        "file": "case.yaml",
        "hard_veto_count": 0,
        "mandatory_human_control_count": 0,
        "outcome_count": 0,
        "problem_value_defined": False,
        "problem_value_ready": False,
        "residual_case_count": 0,
        "schema_version": 1,
        "status": "valid",
        "task_defined": True,
    }


def test_validate_json_is_deterministic_and_actionable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, {"schema_version": 1, "case": {"unexpected": True}})

    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    first = capsys.readouterr()
    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    second = capsys.readouterr()

    assert first.out == second.out
    assert first.err == second.err == ""
    payload = json.loads(first.out)
    assert payload["status"] == "invalid"
    assert payload["exit_code"] == 12
    assert payload["diagnostics"]
    for diagnostic in payload["diagnostics"]:
        assert set(diagnostic) == {"field", "file", "id", "message", "remediation", "requirement"}


def test_validate_quiet_preserves_failure_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "missing"

    assert main(["validate", str(workspace), "--quiet"]) == ExitCode.VALIDATION_FAILED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_json_and_quiet_are_mutually_exclusive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["validate", str(tmp_path), "--json", "--quiet"])
    assert caught.value.code == ExitCode.USAGE


def test_internal_error_maps_to_stable_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(_path: Path) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr("archsift.cli.validate_workspace", boom)

    assert main(["validate", str(tmp_path)]) == ExitCode.INTERNAL_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "internal-error" in captured.err


def test_pathologically_nested_yaml_is_malformed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "case.yaml").write_text("[" * 50_000 + "]" * 50_000)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "malformed-yaml"


@pytest.mark.skipif(os.name == "nt", reason="Windows CI may not permit unprivileged symlinks")
def test_case_file_symlink_loop_is_unsafe_path(tmp_path: Path) -> None:
    workspace = tmp_path / "case"
    workspace.mkdir()
    (workspace / "case.yaml").symlink_to("case.yaml")

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.UNSAFE_PATH
    assert result.diagnostics[0].id == "case-file-unresolvable"


@pytest.mark.skipif(os.name == "nt", reason="Windows CI may not permit unprivileged symlinks")
def test_workspace_symlink_loop_is_unsafe_path(tmp_path: Path) -> None:
    loop = tmp_path / "loop"
    loop.symlink_to("loop")

    result = validate_workspace(loop)

    assert result.exit_code == ExitCode.UNSAFE_PATH
    assert result.diagnostics[0].id == "workspace-unresolvable"


def test_utf8_bom_in_case_yaml_is_accepted(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "case.yaml").write_bytes(
        b"\xef\xbb\xbf" + b"schema_version: 1\ncase: {id: x, title: X}\n"
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.case.id == "x"


@pytest.mark.parametrize(
    "content",
    [
        "schema_version: 2\nschema_version: 1\ncase: {id: x, title: X}\n",
        "schema_version: 1\ncase:\n  id: a\n  id: b\n  title: X\n",
    ],
)
def test_duplicate_mapping_keys_are_rejected(tmp_path: Path, content: str) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "case.yaml").write_text(content)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "malformed-yaml"
    assert "duplicate key" in result.diagnostics[0].message


def test_malformed_yaml_diagnostics_are_path_independent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _workspace(tmp_path / "one")
    second = _workspace(tmp_path / "two")
    content = "case: [\n"
    (first / "case.yaml").write_text(content)
    (second / "case.yaml").write_text(content)

    result_first = validate_workspace(first)
    result_second = validate_workspace(second)

    assert result_first.exit_code == result_second.exit_code == ExitCode.MALFORMED_INPUT
    assert [d.to_dict() for d in result_first.diagnostics] == [
        d.to_dict() for d in result_second.diagnostics
    ]
    message = result_first.diagnostics[0].message
    assert str(first) not in message
    assert str(second) not in message

    assert main(["validate", str(first), "--json"]) == ExitCode.MALFORMED_INPUT
    first_json = capsys.readouterr().out
    assert main(["validate", str(second), "--json"]) == ExitCode.MALFORMED_INPUT
    second_json = capsys.readouterr().out
    assert first_json == second_json


def test_complete_problem_value_validates_as_typed_immutable_objects(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": _problem_evidence(),
            "problem_value": _problem_value(),
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    problem = result.dossier.problem_value
    assert isinstance(problem, ProblemValue)
    assert [item.id for item in problem.outcomes] == ["reduce-time", "compare-capacity"]
    assert all(isinstance(item, ProblemOutcome) for item in problem.outcomes)
    assert all(isinstance(item, ProblemBaseline) for item in problem.baselines)
    assert all(isinstance(item, ProblemConstraint) for item in problem.constraints)
    assert problem.affected_volume.evidence_ids == ("volume-assumption",)
    assert evaluate_problem_value_readiness(result.dossier).ready is True
    with pytest.raises(FrozenInstanceError):
        problem.outcomes[0].target = "Changed"  # type: ignore[misc]


def test_absent_problem_value_is_valid_but_not_ready(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_problem_value_readiness(result.dossier)
    assert readiness.ready is False
    assert [finding.id for finding in readiness.findings] == ["problem-value-missing"]
    assert readiness.findings[0].field == "$.problem_value"


@pytest.mark.parametrize(
    "missing_field",
    [
        "outcomes",
        "baselines",
        "constraints",
        "affected_volume",
        "material_pain",
        "error_cost",
        "technology_limitation",
    ],
)
def test_every_problem_value_section_is_required(tmp_path: Path, missing_field: str) -> None:
    workspace = _workspace(tmp_path)
    problem = _problem_value()
    del problem[missing_field]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": _problem_evidence(),
            "problem_value": problem,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-005"
    assert missing_field in result.diagnostics[0].remediation


@pytest.mark.parametrize(
    ("record", "missing_field"),
    [
        ("outcome", "id"),
        ("outcome", "description"),
        ("outcome", "measure"),
        ("outcome", "target"),
        ("outcome", "baseline_id"),
        ("outcome", "binding"),
        ("outcome", "evidence_ids"),
        ("baseline", "id"),
        ("baseline", "description"),
        ("baseline", "measure"),
        ("baseline", "value"),
        ("baseline", "evidence_ids"),
        ("constraint", "id"),
        ("constraint", "description"),
        ("constraint", "test"),
        ("constraint", "required_result"),
        ("constraint", "binding"),
        ("constraint", "evidence_ids"),
        ("statement", "statement"),
        ("statement", "evidence_ids"),
    ],
)
def test_every_problem_value_record_field_is_required(
    tmp_path: Path, record: str, missing_field: str
) -> None:
    workspace = _workspace(tmp_path)
    problem = _problem_value()
    if record == "outcome":
        target = cast(list[dict[str, object]], problem["outcomes"])[0]
    elif record == "baseline":
        target = cast(list[dict[str, object]], problem["baselines"])[0]
    elif record == "constraint":
        target = cast(list[dict[str, object]], problem["constraints"])[0]
    else:
        target = cast(dict[str, object], problem["affected_volume"])
    del target[missing_field]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": _problem_evidence(),
            "problem_value": problem,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-005"
    assert missing_field in result.diagnostics[0].remediation


@pytest.mark.parametrize(
    ("record", "field"),
    [
        ("outcome", "id"),
        ("outcome", "description"),
        ("outcome", "measure"),
        ("outcome", "target"),
        ("outcome", "baseline_id"),
        ("outcome", "evidence_ids"),
        ("baseline", "id"),
        ("baseline", "description"),
        ("baseline", "measure"),
        ("baseline", "value"),
        ("baseline", "evidence_ids"),
        ("constraint", "id"),
        ("constraint", "description"),
        ("constraint", "test"),
        ("constraint", "required_result"),
        ("constraint", "evidence_ids"),
        ("statement", "statement"),
        ("statement", "evidence_ids"),
    ],
)
def test_all_problem_value_strings_require_visible_content(
    tmp_path: Path, record: str, field: str
) -> None:
    workspace = _workspace(tmp_path)
    problem = _problem_value()
    if record == "outcome":
        target = cast(list[dict[str, object]], problem["outcomes"])[0]
    elif record == "baseline":
        target = cast(list[dict[str, object]], problem["baselines"])[0]
    elif record == "constraint":
        target = cast(list[dict[str, object]], problem["constraints"])[0]
    else:
        target = cast(dict[str, object], problem["affected_volume"])
    target[field] = [" \t "] if field == "evidence_ids" else " \t "
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": _problem_evidence(),
            "problem_value": problem,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-005"
    assert "non-whitespace" in result.diagnostics[0].remediation


def test_explicit_empty_problem_constraints_are_valid(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    problem = _problem_value()
    problem["constraints"] = []
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": _problem_evidence(),
            "problem_value": problem,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.problem_value is not None
    assert result.dossier.problem_value.constraints == ()


@pytest.mark.parametrize("value", [None, [], "value", 42])
def test_problem_value_must_be_an_object_when_supplied(tmp_path: Path, value: object) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "problem_value": value,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-005"


def test_problem_value_unknown_and_whitespace_fields_fail_closed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    problem = _problem_value()
    outcomes = cast(list[dict[str, object]], problem["outcomes"])
    outcomes[0]["description"] = " \t "
    outcomes[0]["unexpected"] = "inert"
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": _problem_evidence(),
            "problem_value": problem,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert all(item.requirement == "FR-005" for item in result.diagnostics)
    assert {item.id for item in result.diagnostics} == {"schema-validation-failed", "unknown-field"}


def test_unquoted_problem_binding_yes_does_not_become_boolean(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    payload = {
        "schema_version": 1,
        "case": {"id": "x", "title": "X"},
        "evidence": _problem_evidence(),
        "problem_value": _problem_value(),
    }
    content = yaml.safe_dump(payload, sort_keys=False).replace("binding: true", "binding: yes", 1)
    (workspace / "case.yaml").write_text(content)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].field == "$.problem_value.outcomes[0].binding"
    assert result.diagnostics[0].requirement == "FR-005"


def test_problem_criterion_duplicates_share_one_namespace(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    problem = _problem_value()
    outcomes = cast(list[dict[str, object]], problem["outcomes"])
    constraints = cast(list[dict[str, object]], problem["constraints"])
    outcomes[1]["id"] = outcomes[0]["id"]
    constraints[0]["id"] = outcomes[0]["id"]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": _problem_evidence(),
            "problem_value": problem,
        },
    )

    result = validate_workspace(workspace)

    assert [item.id for item in result.diagnostics] == [
        "duplicate-problem-criterion-id",
        "duplicate-problem-criterion-id",
    ]
    assert [item.field for item in result.diagnostics] == [
        "$.problem_value.constraints[0].id",
        "$.problem_value.outcomes[1].id",
    ]
    assert all("$.problem_value.outcomes[0].id" in item.message for item in result.diagnostics)


def test_duplicate_baselines_and_missing_baseline_references_are_exact(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    problem = _problem_value()
    baselines = cast(list[dict[str, object]], problem["baselines"])
    baselines[1]["id"] = baselines[0]["id"]
    outcomes = cast(list[dict[str, object]], problem["outcomes"])
    outcomes[1]["baseline_id"] = "absent"
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": _problem_evidence(),
            "problem_value": problem,
        },
    )

    result = validate_workspace(workspace)

    assert [(item.id, item.field) for item in result.diagnostics] == [
        ("duplicate-problem-baseline-id", "$.problem_value.baselines[1].id"),
        ("missing-problem-baseline-reference", "$.problem_value.outcomes[1].baseline_id"),
    ]


@pytest.mark.parametrize(
    ("target", "expected_path"),
    [
        ("outcome", "$.problem_value.outcomes[0].evidence_ids[0]"),
        ("baseline", "$.problem_value.baselines[0].evidence_ids[0]"),
        ("constraint", "$.problem_value.constraints[0].evidence_ids[0]"),
        ("statement", "$.problem_value.error_cost.evidence_ids[0]"),
    ],
)
def test_missing_problem_evidence_references_are_exact(
    tmp_path: Path, target: str, expected_path: str
) -> None:
    workspace = _workspace(tmp_path)
    problem = _problem_value()
    if target == "outcome":
        cast(list[dict[str, object]], problem["outcomes"])[0]["evidence_ids"] = ["absent"]
    elif target == "baseline":
        cast(list[dict[str, object]], problem["baselines"])[0]["evidence_ids"] = ["absent"]
    elif target == "constraint":
        cast(list[dict[str, object]], problem["constraints"])[0]["evidence_ids"] = ["absent"]
    else:
        cast(dict[str, object], problem["error_cost"])["evidence_ids"] = ["absent"]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": _problem_evidence(),
            "problem_value": problem,
        },
    )

    result = validate_workspace(workspace)

    matches = [
        item for item in result.diagnostics if item.id == "missing-problem-value-evidence-reference"
    ]
    assert len(matches) == 1
    assert matches[0].field == expected_path
    assert matches[0].requirement == "FR-005"


def test_problem_evidence_must_be_classified_for_problem_value(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _problem_evidence()
    evidence[0]["affects"] = ["comparative-fit"]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": evidence,
            "problem_value": _problem_value(),
        },
    )

    result = validate_workspace(workspace)

    mismatches = [
        item for item in result.diagnostics if item.id == "problem-value-evidence-area-mismatch"
    ]
    assert [item.field for item in mismatches] == [
        "$.problem_value.baselines[0].evidence_ids[0]",
        "$.problem_value.error_cost.evidence_ids[0]",
        "$.problem_value.material_pain.evidence_ids[0]",
        "$.problem_value.outcomes[0].evidence_ids[0]",
    ]


@pytest.mark.parametrize(
    ("kind", "ready"),
    [("observed", True), ("estimate", True), ("assumption", False), ("missing", False)],
)
def test_baseline_evidence_kind_controls_readiness(tmp_path: Path, kind: str, ready: bool) -> None:
    workspace = _workspace(tmp_path)
    evidence = [_entry(kind, "baseline-observed"), _entry("assumption", "volume-assumption")]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": evidence,
            "problem_value": _problem_value(),
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_problem_value_readiness(result.dossier)
    assert readiness.ready is ready
    assert [finding.id for finding in readiness.findings] == (
        [] if ready else ["credible-baseline-missing"]
    )


@pytest.mark.parametrize(
    ("kind", "metadata_field"),
    [("observed", "provenance"), ("estimate", "method")],
)
def test_blank_credibility_metadata_cannot_make_a_baseline_ready(
    tmp_path: Path, kind: str, metadata_field: str
) -> None:
    workspace = _workspace(tmp_path)
    baseline = _entry(kind, "baseline-observed")
    baseline[metadata_field] = " \t "
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [baseline, _entry("assumption", "volume-assumption")],
            "problem_value": _problem_value(),
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_problem_value_readiness(result.dossier)
    assert readiness.ready is False
    assert [finding.id for finding in readiness.findings] == ["credible-baseline-missing"]


def test_baseline_with_any_observed_or_estimate_entry_is_credible(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = [
        _entry("assumption", "volume-assumption"),
        _entry("observed", "baseline-observed"),
        _entry("estimate", "est"),
    ]
    problem = _problem_value()
    baselines = cast(list[dict[str, object]], problem["baselines"])
    baselines[0]["evidence_ids"] = ["volume-assumption", "baseline-observed"]
    baselines[1]["evidence_ids"] = ["est", "volume-assumption"]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": evidence,
            "problem_value": problem,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_problem_value_readiness(result.dossier)
    assert readiness.ready is True
    assert readiness.findings == ()


def test_baseline_and_criterion_ids_use_separate_namespaces(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    problem = _problem_value()
    outcome_id = cast(str, cast(list[dict[str, object]], problem["outcomes"])[0]["id"])
    baselines = cast(list[dict[str, object]], problem["baselines"])
    baselines[0]["id"] = outcome_id
    outcomes = cast(list[dict[str, object]], problem["outcomes"])
    outcomes[0]["baseline_id"] = outcome_id
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": _problem_evidence(),
            "problem_value": problem,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.diagnostics == ()


def test_multi_document_yaml_is_malformed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "case.yaml").write_text(
        "schema_version: 1\ncase: {id: x, title: X}\n---\nschema_version: 1\n"
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "malformed-yaml"


def test_every_binding_outcome_requires_a_credible_baseline(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    problem = _problem_value()
    outcomes = cast(list[dict[str, object]], problem["outcomes"])
    outcomes[1]["binding"] = True
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": _problem_evidence(),
            "problem_value": problem,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_problem_value_readiness(result.dossier)
    assert readiness.ready is False
    assert [(finding.id, finding.field) for finding in readiness.findings] == [
        ("credible-baseline-missing", "$.problem_value.outcomes[1].baseline_id")
    ]


def test_readiness_requires_at_least_one_binding_outcome(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    problem = _problem_value()
    for outcome in cast(list[dict[str, object]], problem["outcomes"]):
        outcome["binding"] = False
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": _problem_evidence(),
            "problem_value": problem,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_problem_value_readiness(result.dossier)
    assert readiness.ready is False
    assert [finding.id for finding in readiness.findings] == ["binding-outcome-missing"]


def test_validate_json_reports_problem_value_readiness(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": _problem_evidence(),
            "problem_value": _problem_value(),
        },
    )

    assert main(["validate", str(workspace), "--json"]) == ExitCode.SUCCESS
    payload = json.loads(capsys.readouterr().out)
    assert payload["problem_value_defined"] is True
    assert payload["problem_value_ready"] is True
    assert payload["outcome_count"] == 2
    assert payload["constraint_count"] == 1


def test_template_problem_value_example_is_valid_and_ready(tmp_path: Path) -> None:
    guidance = (
        files("archsift").joinpath("templates/workspace-README.md").read_text(encoding="utf-8")
    )
    blocks = guidance.split("```yaml")
    evidence_example = yaml.safe_load(blocks[2].split("```", 1)[0])
    problem_example = yaml.safe_load(blocks[3].split("```", 1)[0])
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": evidence_example["evidence"],
            "problem_value": problem_example["problem_value"],
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert evaluate_problem_value_readiness(result.dossier).ready is True


@pytest.mark.parametrize("value", [None, [], "agency", 42])
def test_agency_necessity_must_be_an_object_when_supplied(tmp_path: Path, value: object) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "agency_necessity": value,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-006"


def test_raw_unquoted_yes_no_agency_answers_remain_strings(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    payload = {
        "schema_version": 1,
        "case": {"id": "x", "title": "X"},
        "evidence": [_agency_evidence()],
        "agency_necessity": _agency_necessity(),
    }
    content = yaml.safe_dump(payload, sort_keys=False)
    content = content.replace("answer: 'yes'", "answer: yes").replace("answer: 'no'", "answer: no")
    (workspace / "case.yaml").write_text(content)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.agency_necessity is not None
    assert result.dossier.agency_necessity.runtime_tool_choice_required.answer is AgencyAnswer.YES
    assert result.dossier.agency_necessity.execution_steps_predefinable.answer is AgencyAnswer.NO


def test_agency_text_is_inert_and_does_not_open_named_paths(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "does-not-exist" / "tool-result.txt"
    agency = _agency_necessity()
    cast(dict[str, object], agency["runtime_replanning_required"])["rationale"] = str(outside)
    residual = cast(list[dict[str, object]], agency["residual_cases"])[0]
    residual["fixed_workflow_failure"] = str(outside)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence()],
            "agency_necessity": agency,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.agency_necessity is not None
    assert result.dossier.agency_necessity.runtime_replanning_required.rationale == str(outside)
    assert not outside.exists()


def test_complete_agency_necessity_validates_as_typed_immutable_objects(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    agency = _agency_necessity()
    residuals = cast(list[dict[str, object]], agency["residual_cases"])
    residuals.append(
        {
            "id": "new-feedback",
            "description": "A tool result changes the remaining checks.",
            "fixed_workflow_failure": "The later check order cannot be selected in advance.",
            "evidence_ids": ["agency-observed"],
        }
    )
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence()],
            "agency_necessity": agency,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    facts = result.dossier.agency_necessity
    assert isinstance(facts, AgencyNecessity)
    assert isinstance(facts.execution_steps_predefinable, AgencyQuestion)
    assert facts.execution_steps_predefinable.answer is AgencyAnswer.NO
    assert [case.id for case in facts.residual_cases] == [
        "evidence-dependent-follow-up",
        "new-feedback",
    ]
    assert all(isinstance(case, ResidualCase) for case in facts.residual_cases)
    assert evaluate_agency_necessity_readiness(result.dossier).ready is True
    with pytest.raises(FrozenInstanceError):
        facts.runtime_replanning_required.rationale = "Changed"  # type: ignore[misc]


def test_absent_agency_necessity_is_valid_but_not_ready(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_agency_necessity_readiness(result.dossier)
    assert readiness.ready is False
    assert [finding.id for finding in readiness.findings] == ["agency-necessity-missing"]
    assert readiness.findings[0].field == "$.agency_necessity"


@pytest.mark.parametrize(
    "missing_field",
    [
        "execution_steps_predefinable",
        "step_count_or_order_predictable",
        "runtime_tool_choice_required",
        "runtime_replanning_required",
        "environmental_feedback_available",
        "completion_independently_verifiable",
        "effects_independently_verifiable",
        "fixed_workflow_sufficient",
        "residual_cases",
    ],
)
def test_every_agency_necessity_field_is_required(tmp_path: Path, missing_field: str) -> None:
    workspace = _workspace(tmp_path)
    agency = _agency_necessity()
    del agency[missing_field]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence()],
            "agency_necessity": agency,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-006"
    assert missing_field in result.diagnostics[0].remediation


@pytest.mark.parametrize("missing_field", ["answer", "rationale", "evidence_ids"])
def test_every_agency_question_field_is_required(tmp_path: Path, missing_field: str) -> None:
    workspace = _workspace(tmp_path)
    agency = _agency_necessity()
    question = cast(dict[str, object], agency["runtime_replanning_required"])
    del question[missing_field]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence()],
            "agency_necessity": agency,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-006"
    assert missing_field in result.diagnostics[0].remediation


@pytest.mark.parametrize(
    "missing_field", ["id", "description", "fixed_workflow_failure", "evidence_ids"]
)
def test_every_residual_case_field_is_required(tmp_path: Path, missing_field: str) -> None:
    workspace = _workspace(tmp_path)
    agency = _agency_necessity()
    residual = cast(list[dict[str, object]], agency["residual_cases"])[0]
    del residual[missing_field]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence()],
            "agency_necessity": agency,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-006"
    assert missing_field in result.diagnostics[0].remediation


@pytest.mark.parametrize(
    ("target", "value"),
    [
        ("answer", "maybe"),
        ("rationale", " \t "),
        ("question_evidence", [" \t "]),
        ("residual_id", " \t "),
        ("residual_description", " \t "),
        ("residual_failure", " \t "),
        ("residual_evidence", [" \t "]),
        ("duplicate_question_evidence", ["agency-observed", "agency-observed"]),
        ("duplicate_residual_evidence", ["agency-observed", "agency-observed"]),
    ],
)
def test_agency_values_fail_closed(tmp_path: Path, target: str, value: object) -> None:
    workspace = _workspace(tmp_path)
    agency = _agency_necessity()
    question = cast(dict[str, object], agency["runtime_replanning_required"])
    residual = cast(list[dict[str, object]], agency["residual_cases"])[0]
    locations = {
        "answer": (question, "answer"),
        "rationale": (question, "rationale"),
        "question_evidence": (question, "evidence_ids"),
        "residual_id": (residual, "id"),
        "residual_description": (residual, "description"),
        "residual_failure": (residual, "fixed_workflow_failure"),
        "residual_evidence": (residual, "evidence_ids"),
        "duplicate_question_evidence": (question, "evidence_ids"),
        "duplicate_residual_evidence": (residual, "evidence_ids"),
    }
    record, field = locations[target]
    record[field] = value
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence()],
            "agency_necessity": agency,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-006"
    assert result.diagnostics[0].remediation


def test_agency_proxy_and_unknown_nested_fields_fail_closed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    agency = _agency_necessity()
    agency["agent_needed"] = True
    agency["documents"] = True
    question = cast(dict[str, object], agency["runtime_tool_choice_required"])
    question["many_steps"] = True
    residual = cast(list[dict[str, object]], agency["residual_cases"])[0]
    residual["legacy_system"] = True
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence()],
            "agency_necessity": agency,
        },
    )

    result = validate_workspace(workspace)

    assert [(item.id, item.field, item.requirement) for item in result.diagnostics] == [
        ("unknown-field", "$.agency_necessity.agent_needed", "FR-006"),
        ("unknown-field", "$.agency_necessity.documents", "FR-006"),
        (
            "unknown-field",
            "$.agency_necessity.residual_cases[0].legacy_system",
            "FR-006",
        ),
        (
            "unknown-field",
            "$.agency_necessity.runtime_tool_choice_required.many_steps",
            "FR-006",
        ),
    ]


def test_fixed_workflow_no_requires_a_residual_case(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    agency = _agency_necessity()
    agency["residual_cases"] = []
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence()],
            "agency_necessity": agency,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].field == "$.agency_necessity.residual_cases"
    assert result.diagnostics[0].requirement == "FR-006"


def test_fixed_workflow_yes_requires_no_residual_cases(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    agency = _agency_necessity("yes")
    agency["residual_cases"] = _agency_necessity("no")["residual_cases"]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence()],
            "agency_necessity": agency,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].field == "$.agency_necessity.residual_cases"
    assert result.diagnostics[0].requirement == "FR-006"
    assert "empty" in result.diagnostics[0].remediation


def test_unknown_fixed_workflow_may_preserve_residual_cases_but_is_not_ready(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    agency = _agency_necessity("unknown")
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence()],
            "agency_necessity": agency,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_agency_necessity_readiness(result.dossier)
    assert readiness.ready is False
    assert [(item.id, item.field) for item in readiness.findings] == [
        ("agency-answer-unknown", "$.agency_necessity.fixed_workflow_sufficient.answer")
    ]


def test_duplicate_residual_case_ids_identify_every_later_case(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    agency = _agency_necessity()
    residuals = cast(list[dict[str, object]], agency["residual_cases"])
    residuals.extend([dict(residuals[0]), dict(residuals[0])])
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence()],
            "agency_necessity": agency,
        },
    )

    result = validate_workspace(workspace)

    assert [item.field for item in result.diagnostics] == [
        "$.agency_necessity.residual_cases[1].id",
        "$.agency_necessity.residual_cases[2].id",
    ]
    assert all(item.id == "duplicate-residual-case-id" for item in result.diagnostics)
    assert all("residual_cases[0].id" in item.message for item in result.diagnostics)


@pytest.mark.parametrize(
    ("target", "expected_path"),
    [
        (
            "question",
            "$.agency_necessity.runtime_replanning_required.evidence_ids[0]",
        ),
        ("residual", "$.agency_necessity.residual_cases[0].evidence_ids[0]"),
    ],
)
def test_missing_agency_evidence_references_are_exact(
    tmp_path: Path, target: str, expected_path: str
) -> None:
    workspace = _workspace(tmp_path)
    agency = _agency_necessity()
    if target == "question":
        cast(dict[str, object], agency["runtime_replanning_required"])["evidence_ids"] = ["absent"]
    else:
        cast(list[dict[str, object]], agency["residual_cases"])[0]["evidence_ids"] = ["absent"]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence()],
            "agency_necessity": agency,
        },
    )

    result = validate_workspace(workspace)

    matches = [
        item for item in result.diagnostics if item.id == "missing-agency-evidence-reference"
    ]
    assert len(matches) == 1
    assert matches[0].field == expected_path
    assert matches[0].requirement == "FR-006"


def test_agency_evidence_must_be_classified_for_agency_necessity(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _agency_evidence()
    evidence["affects"] = ["comparative-fit"]
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [evidence],
            "agency_necessity": _agency_necessity(),
        },
    )

    result = validate_workspace(workspace)

    mismatches = [item for item in result.diagnostics if item.id == "agency-evidence-area-mismatch"]
    assert len(mismatches) == 9
    assert all(item.requirement == "FR-006" for item in mismatches)
    assert (
        mismatches[0].field
        == "$.agency_necessity.completion_independently_verifiable.evidence_ids[0]"
    )
    assert (
        mismatches[-1].field == "$.agency_necessity.step_count_or_order_predictable.evidence_ids[0]"
    )


@pytest.mark.parametrize(
    ("kind", "ready"),
    [("observed", True), ("estimate", True), ("assumption", False), ("missing", False)],
)
def test_agency_evidence_kind_controls_readiness(tmp_path: Path, kind: str, ready: bool) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence(kind)],
            "agency_necessity": _agency_necessity(),
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_agency_necessity_readiness(result.dossier)
    assert readiness.ready is ready
    if ready:
        assert readiness.findings == ()
    else:
        assert len(readiness.findings) == 9
        assert all("credible" in finding.id for finding in readiness.findings)


@pytest.mark.parametrize(
    ("kind", "metadata_field"),
    [("observed", "provenance"), ("estimate", "method")],
)
def test_blank_agency_credibility_metadata_cannot_make_readiness_true(
    tmp_path: Path, kind: str, metadata_field: str
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _agency_evidence(kind)
    evidence[metadata_field] = " \t "
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [evidence],
            "agency_necessity": _agency_necessity(),
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert evaluate_agency_necessity_readiness(result.dossier).ready is False


def test_unknown_question_and_uncertain_evidence_produce_ordered_findings(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    agency = _agency_necessity()
    cast(dict[str, object], agency["runtime_replanning_required"])["answer"] = "unknown"
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence("assumption")],
            "agency_necessity": agency,
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    first = evaluate_agency_necessity_readiness(result.dossier)
    second = evaluate_agency_necessity_readiness(result.dossier)
    assert first == second
    assert first.ready is False
    replanning = [
        (finding.id, finding.field)
        for finding in first.findings
        if ".runtime_replanning_required." in finding.field
    ]
    assert replanning == [
        ("agency-answer-unknown", "$.agency_necessity.runtime_replanning_required.answer"),
        (
            "credible-agency-evidence-missing",
            "$.agency_necessity.runtime_replanning_required.evidence_ids",
        ),
    ]


def test_validate_json_reports_agency_necessity_readiness(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": [_agency_evidence()],
            "agency_necessity": _agency_necessity(),
        },
    )

    assert main(["validate", str(workspace), "--json"]) == ExitCode.SUCCESS
    payload = json.loads(capsys.readouterr().out)
    assert payload["agency_necessity_defined"] is True
    assert payload["agency_necessity_ready"] is True
    assert payload["residual_case_count"] == 1
    assert "agent_needed" not in payload
    assert "verdict" not in payload


def test_template_agency_example_is_valid_and_ready(tmp_path: Path) -> None:
    guidance = (
        files("archsift").joinpath("templates/workspace-README.md").read_text(encoding="utf-8")
    )
    blocks = guidance.split("```yaml")
    evidence_example = yaml.safe_load(blocks[2].split("```", 1)[0])
    agency_example = yaml.safe_load(blocks[4].split("```", 1)[0])
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        {
            "schema_version": 1,
            "case": {"id": "x", "title": "X"},
            "evidence": evidence_example["evidence"],
            "agency_necessity": agency_example["agency_necessity"],
        },
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert evaluate_agency_necessity_readiness(result.dossier).ready is True
