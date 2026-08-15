from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from archsift.canonical import JsonObject, canonical_json_bytes
from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.graph_change import (
    GraphChangeError,
    GraphChangeFailure,
    load_graph_change_proposal,
    validate_graph_change,
)
from archsift.knowledge_graph import (
    Citation,
    Lifecycle,
    Node,
    NodeKind,
    Relation,
    RelationKind,
    Snapshot,
    Stance,
    build_snapshot,
    canonical_snapshot_bytes,
    load_snapshot,
    node_content_identity,
    relation_content_identity,
    snapshot_reference,
)

_GOLDEN = Path(__file__).parent / "golden" / "graph-snapshot-v1.json"


def _snapshot() -> Snapshot:
    return load_snapshot(_GOLDEN.read_bytes())


def _entry_map(snapshot: Snapshot | None) -> dict[tuple[str, str], Node | Relation]:
    if snapshot is None:
        return {}
    return {
        **{("node", node.id): node for node in snapshot.nodes},
        **{("relation", relation.id): relation for relation in snapshot.relations},
    }


def _identity(entry: Node | Relation) -> str:
    if isinstance(entry, Node):
        return node_content_identity(entry)
    return relation_content_identity(entry)


def _sources(entry: Node | Relation) -> list[str]:
    if isinstance(entry, Node) and entry.kind is NodeKind.EVIDENCE_SOURCE:
        return [entry.id]
    return sorted(citation.source_id for citation in entry.citations)


def _proposal(
    proposed: Snapshot,
    base: Snapshot | None = None,
    *,
    rationale: dict[tuple[str, str], str] | None = None,
    behavior_change: bool = False,
) -> JsonObject:
    old = _entry_map(base)
    new = _entry_map(proposed)
    changes: list[JsonObject] = []
    for entry_kind, identifier in sorted(set(old) | set(new)):
        key = (entry_kind, identifier)
        if key not in old:
            delta = "added"
            entry = new[key]
        elif key not in new:
            delta = "removed"
            entry = old[key]
        elif _identity(old[key]) != _identity(new[key]):
            delta = "changed"
            entry = new[key]
        else:
            continue
        changes.append(
            {
                "delta": delta,
                "entry_kind": entry_kind,
                "evidence_source_ids": _sources(entry),
                "id": identifier,
                "rationale": (rationale or {}).get(
                    key,
                    {"added": "addition", "changed": "correction", "removed": "removal"}[delta],
                ),
            }
        )
    return {
        "attestations": {
            "independently_authored_synthetic_material": True,
            "no_case_material_or_derivative": True,
            "open_world_absence_is_not_evidence": True,
        },
        "base_snapshot": None if base is None else snapshot_reference(base),
        "behavior_change": behavior_change,
        "change_id": "synthetic-graph-change",
        "change_kind": "initial-publication" if base is None else "evolution",
        "change_schema_version": 1,
        "changes": changes,
        "proposed_snapshot": snapshot_reference(proposed),
        "public_issue": "https://github.com/maximalfocus/archsift/issues/97",
        "regression_test_ids": ["test-synthetic-change"] if behavior_change else [],
        "synthetic_counterexample_ids": ["synthetic-counterexample"] if behavior_change else [],
    }


def _changed_node(
    base: Snapshot, identifier: str, **updates: object
) -> tuple[list[Node], list[Relation]]:
    nodes = [replace(node, **updates) if node.id == identifier else node for node in base.nodes]
    return nodes, list(base.relations)


def test_valid_initial_publication_is_canonical_and_exact() -> None:
    proposed = _snapshot()
    proposal = _proposal(proposed)
    loaded = load_graph_change_proposal(canonical_json_bytes(proposal))

    summary = validate_graph_change(loaded, proposed)

    assert summary["change_kind"] == "initial-publication"
    assert summary["changed_entry_count"] == len(proposed.nodes) + len(proposed.relations)
    assert summary["node_changes"] == {
        "added": len(proposed.nodes),
        "changed": 0,
        "removed": 0,
    }
    assert summary["relation_changes"] == {
        "added": len(proposed.relations),
        "changed": 0,
        "removed": 0,
    }


@pytest.mark.parametrize(
    ("make_proposed", "rationale", "key"),
    [
        (
            lambda base: build_snapshot(
                [
                    *base.nodes,
                    Node(
                        id="new-independent-concept",
                        kind=NodeKind.CONCEPT,
                        label="Independent synthetic concept",
                        statement="A new independently authored synthetic concept.",
                        lifecycle=Lifecycle.PROPOSED,
                        citations=(Citation(source_id="source-primary", stance=Stance.SUPPORTS),),
                    ),
                ],
                base.relations,
            ),
            "addition",
            ("node", "new-independent-concept"),
        ),
        (
            lambda base: build_snapshot(
                *_changed_node(
                    base,
                    "runtime-agency",
                    statement="A corrected independently authored synthetic statement.",
                )
            ),
            "correction",
            ("node", "runtime-agency"),
        ),
        (
            lambda base: build_snapshot(
                *_changed_node(base, "runtime-agency", lifecycle=Lifecycle.CHALLENGED)
            ),
            "challenge",
            ("node", "runtime-agency"),
        ),
        (
            lambda base: build_snapshot(
                [
                    replace(node, lifecycle=Lifecycle.SUPERSEDED)
                    if node.id == "agency-needs-open-tool-choice"
                    else node
                    for node in base.nodes
                ],
                base.relations,
            ),
            "supersession",
            ("node", "agency-needs-open-tool-choice"),
        ),
        (
            lambda base: build_snapshot(
                *_changed_node(base, "runtime-agency", lifecycle=Lifecycle.DEPRECATED)
            ),
            "deprecation",
            ("node", "runtime-agency"),
        ),
        (
            lambda base: build_snapshot(
                base.nodes,
                [
                    relation
                    for relation in base.relations
                    if relation.id != "pattern-specialises-class"
                ],
            ),
            "removal",
            ("relation", "pattern-specialises-class"),
        ),
        (
            lambda base: build_snapshot(
                base.nodes,
                [
                    *base.relations,
                    Relation(
                        id="counterexample-challenges-rule",
                        kind=RelationKind.CHALLENGES,
                        subject_id="fixed-workflow-sufficed",
                        object_id="agency-necessity-rule",
                        statement="The synthetic counterexample challenges the rule.",
                        lifecycle=Lifecycle.SUPPORTED,
                        citations=(
                            Citation(source_id="source-secondary", stance=Stance.CHALLENGES),
                        ),
                    ),
                ],
            ),
            "challenge",
            ("relation", "counterexample-challenges-rule"),
        ),
        (
            lambda base: build_snapshot(
                base.nodes,
                [
                    *base.relations,
                    Relation(
                        id="open-tool-theory-supersedes-step-theory",
                        kind=RelationKind.SUPERSEDES,
                        subject_id="agency-needs-open-tool-choice",
                        object_id="agency-needs-unpredictable-steps",
                        statement="One synthetic theory supersedes another for this proof.",
                        lifecycle=Lifecycle.PROPOSED,
                        citations=(Citation(source_id="source-primary", stance=Stance.SUPPORTS),),
                    ),
                ],
            ),
            "supersession",
            ("relation", "open-tool-theory-supersedes-step-theory"),
        ),
    ],
)
def test_evolution_accepts_every_visible_rationale(
    make_proposed: Callable[[Snapshot], Snapshot], rationale: str, key: tuple[str, str]
) -> None:
    base = _snapshot()
    proposed = make_proposed(base)
    proposal = _proposal(proposed, base, rationale={key: rationale})

    summary = validate_graph_change(proposal, proposed, base)

    assert summary["changed_entry_count"] == 1


@pytest.mark.parametrize("mutation", ["missing", "invented"])
def test_exact_diff_rejects_missing_or_invented_delta(mutation: str) -> None:
    base = _snapshot()
    nodes, relations = _changed_node(base, "runtime-agency", statement="Corrected synthetic text.")
    proposed = build_snapshot(nodes, relations)
    proposal = _proposal(proposed, base)
    changes = cast(list[JsonObject], proposal["changes"])
    if mutation == "missing":
        changes.clear()
    else:
        changes.append(
            {
                "delta": "added",
                "entry_kind": "relation",
                "evidence_source_ids": ["source-primary"],
                "id": "invented-delta",
                "rationale": "addition",
            }
        )

    with pytest.raises(GraphChangeError) as caught:
        validate_graph_change(proposal, proposed, base)

    assert caught.value.category is GraphChangeFailure.DELTA_MISMATCH


def test_evidence_mismatch_and_invisible_rationale_fail_closed() -> None:
    base = _snapshot()
    nodes, relations = _changed_node(base, "runtime-agency", statement="Corrected synthetic text.")
    proposed = build_snapshot(nodes, relations)
    proposal = _proposal(proposed, base)
    change = cast(list[JsonObject], proposal["changes"])[0]
    change["evidence_source_ids"] = ["source-secondary"]
    with pytest.raises(GraphChangeError) as caught:
        validate_graph_change(proposal, proposed, base)
    assert caught.value.category is GraphChangeFailure.EVIDENCE_MISMATCH

    change["evidence_source_ids"] = ["source-primary"]
    change["rationale"] = "challenge"
    with pytest.raises(GraphChangeError) as caught:
        validate_graph_change(proposal, proposed, base)
    assert caught.value.category is GraphChangeFailure.INVALID_SEMANTICS


def test_attestations_behavior_proof_order_and_canonicality_are_enforced() -> None:
    proposed = _snapshot()
    proposal = _proposal(proposed)
    attestations = cast(JsonObject, proposal["attestations"])
    attestations["no_case_material_or_derivative"] = False
    with pytest.raises(GraphChangeError) as caught:
        load_graph_change_proposal(canonical_json_bytes(proposal))
    assert caught.value.category is GraphChangeFailure.MALFORMED_PROPOSAL

    proposal = _proposal(proposed)
    proposal["behavior_change"] = True
    with pytest.raises(GraphChangeError) as caught:
        validate_graph_change(proposal, proposed)
    assert caught.value.category is GraphChangeFailure.BEHAVIOR_PROOF_MISSING

    proposal = _proposal(proposed)
    cast(list[JsonObject], proposal["changes"]).reverse()
    with pytest.raises(GraphChangeError) as caught:
        validate_graph_change(proposal, proposed)
    assert caught.value.category is GraphChangeFailure.MALFORMED_PROPOSAL

    with pytest.raises(GraphChangeError) as caught:
        load_graph_change_proposal(json.dumps(_proposal(proposed)).encode())
    assert caught.value.category is GraphChangeFailure.NON_CANONICAL


@pytest.mark.parametrize(
    ("content", "category", "exit_code"),
    [
        (b"\xff", GraphChangeFailure.INVALID_UTF8, ExitCode.MALFORMED_INPUT),
        (b"{", GraphChangeFailure.INVALID_JSON, ExitCode.MALFORMED_INPUT),
        (
            b'{"change_schema_version":1,"change_schema_version":1}\n',
            GraphChangeFailure.INVALID_JSON,
            ExitCode.MALFORMED_INPUT,
        ),
        (
            canonical_json_bytes({"change_schema_version": 99}),
            GraphChangeFailure.UNSUPPORTED_SCHEMA,
            ExitCode.UNSUPPORTED_SCHEMA,
        ),
    ],
)
def test_proposal_loader_classifies_public_failures(
    content: bytes, category: GraphChangeFailure, exit_code: ExitCode
) -> None:
    with pytest.raises(GraphChangeError) as caught:
        load_graph_change_proposal(content)
    assert caught.value.category is category
    assert caught.value.exit_code is exit_code


def _write_inputs(tmp_path: Path, proposal: JsonObject, proposed: Snapshot) -> None:
    (tmp_path / "proposal.json").write_bytes(canonical_json_bytes(proposal))
    (tmp_path / "proposed.json").write_bytes(canonical_snapshot_bytes(proposed))


def test_cli_human_json_quiet_read_only_and_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    proposed = _snapshot()
    proposal = _proposal(proposed)
    _write_inputs(tmp_path, proposal, proposed)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    monkeypatch.chdir(tmp_path)

    assert main(["graph-change", "proposal.json", "proposed.json"]) == ExitCode.SUCCESS
    human = capsys.readouterr().out
    assert "Valid graph change synthetic-graph-change" in human
    assert proposed.snapshot_content_identity in human
    assert "nodes +11 ~0 -0; relations +7 ~0 -0" in human

    assert main(["graph-change", "proposal.json", "proposed.json", "--json"]) == ExitCode.SUCCESS
    output = json.loads(capsys.readouterr().out)
    assert output["graph_change"]["proposed_snapshot"] == snapshot_reference(proposed)
    assert output["graph_change"]["changed_entry_count"] == 18

    assert main(["graph-change", "proposal.json", "proposed.json", "--quiet"]) == ExitCode.SUCCESS
    assert capsys.readouterr() == ("", "")
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before


@pytest.mark.parametrize(
    ("arguments", "exit_code", "diagnostic"),
    [
        (
            ["graph-change", "malformed.json", "proposed.json", "--json"],
            ExitCode.MALFORMED_INPUT,
            "graph-change-invalid-json",
        ),
        (
            ["graph-change", "unsupported.json", "proposed.json", "--json"],
            ExitCode.UNSUPPORTED_SCHEMA,
            "graph-change-unsupported-schema",
        ),
        (
            ["graph-change", "invalid.json", "proposed.json", "--json"],
            ExitCode.VALIDATION_FAILED,
            "graph-change-malformed-proposal",
        ),
        (
            ["graph-change", "../outside.json", "proposed.json", "--json"],
            ExitCode.UNSAFE_PATH,
            "graph-change-target-outside-root",
        ),
        (
            ["graph-change", "missing.json", "proposed.json", "--json"],
            ExitCode.ARTEFACT_UNAVAILABLE,
            "graph-change-target-missing",
        ),
    ],
)
def test_cli_exposes_every_public_failure_class(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    exit_code: ExitCode,
    diagnostic: str,
) -> None:
    proposed = _snapshot()
    (tmp_path / "proposed.json").write_bytes(canonical_snapshot_bytes(proposed))
    (tmp_path / "malformed.json").write_bytes(b"{")
    (tmp_path / "unsupported.json").write_bytes(canonical_json_bytes({"change_schema_version": 99}))
    invalid = _proposal(proposed)
    cast(JsonObject, invalid["attestations"])["no_case_material_or_derivative"] = False
    (tmp_path / "invalid.json").write_bytes(canonical_json_bytes(invalid))
    (tmp_path.parent / "outside.json").write_bytes(canonical_json_bytes(_proposal(proposed)))
    monkeypatch.chdir(tmp_path)

    assert main(arguments) == exit_code

    output = json.loads(capsys.readouterr().out)
    assert output["exit_code"] == exit_code
    assert output["diagnostics"][0]["id"] == diagnostic
    assert output["diagnostics"][0]["requirement"] == "FR-014/FR-015"


def test_cli_requires_base_for_evolution_and_rejects_base_for_initial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _snapshot()
    nodes, relations = _changed_node(base, "runtime-agency", statement="Corrected synthetic text.")
    proposed = build_snapshot(nodes, relations)
    proposal = _proposal(proposed, base)
    _write_inputs(tmp_path, proposal, proposed)
    (tmp_path / "base.json").write_bytes(canonical_snapshot_bytes(base))
    monkeypatch.chdir(tmp_path)

    assert (
        main(["graph-change", "proposal.json", "proposed.json", "--json"])
        == ExitCode.VALIDATION_FAILED
    )
    assert json.loads(capsys.readouterr().out)["diagnostics"][0]["field"] == "$.base_snapshot"

    initial = _proposal(proposed)
    (tmp_path / "proposal.json").write_bytes(canonical_json_bytes(initial))
    assert (
        main(
            [
                "graph-change",
                "proposal.json",
                "proposed.json",
                "--base-snapshot",
                "base.json",
                "--json",
            ]
        )
        == ExitCode.VALIDATION_FAILED
    )
    assert json.loads(capsys.readouterr().out)["diagnostics"][0]["field"] == "$.base_snapshot"
