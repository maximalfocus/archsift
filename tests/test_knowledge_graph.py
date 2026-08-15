from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from dataclasses import replace
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest

from archsift.canonical import canonical_json_bytes
from archsift.case_view import (
    CaseViewError,
    CaseViewRequest,
    FindingBinding,
    construct_case_view,
)
from archsift.diagnostics import ExitCode
from archsift.knowledge_graph import (
    GRAPH_SCHEMA_VERSION,
    Citation,
    DateKind,
    Lifecycle,
    Node,
    NodeKind,
    Relation,
    RelationKind,
    SnapshotError,
    SnapshotFailure,
    Source,
    Stance,
    build_snapshot,
    canonical_snapshot_bytes,
    canonical_snapshot_dict,
    immutable_graph_version,
    load_snapshot,
    snapshot_reference,
)

_GOLDEN = Path(__file__).parent / "golden" / "graph-snapshot-v1.json"

_SUPPORTING = Citation(source_id="source-primary", stance=Stance.SUPPORTS)
_CHALLENGING = Citation(source_id="source-secondary", stance=Stance.CHALLENGES)


def _sources() -> list[Node]:
    return [
        Node(
            id="source-primary",
            kind=NodeKind.EVIDENCE_SOURCE,
            label="Primary synthetic reference",
            statement="An independently authored synthetic reference on control-class trade-offs.",
            lifecycle=Lifecycle.SUPPORTED,
            source=Source(
                locator="urn:example:synthetic-reference-1",
                date_kind=DateKind.PUBLISHED,
                dated=date(2024, 5, 1),
                version="2nd edition",
                publication_state="published",
            ),
        ),
        Node(
            id="source-secondary",
            kind=NodeKind.EVIDENCE_SOURCE,
            label="Secondary synthetic reference",
            statement="An independently authored synthetic counter-reference.",
            lifecycle=Lifecycle.SUPPORTED,
            source=Source(
                locator="urn:example:synthetic-reference-2",
                date_kind=DateKind.RETRIEVED,
                dated=date(2025, 1, 9),
                version=None,
                publication_state="preprint",
            ),
        ),
    ]


def _knowledge() -> tuple[list[Node], list[Relation]]:
    """Return a synthetic corpus exercising every declared node kind."""
    both = (_SUPPORTING, _CHALLENGING)
    nodes = [
        *_sources(),
        Node(
            id="runtime-agency",
            kind=NodeKind.CONCEPT,
            label="Runtime agency",
            statement="A model selects or revises execution steps at run time.",
            lifecycle=Lifecycle.SUPPORTED,
            citations=(_SUPPORTING,),
        ),
        Node(
            id="agentic-control",
            kind=NodeKind.ARCHITECTURE_CLASS,
            label="Agentic control",
            statement="Execution steps and tool choice are decided at run time.",
            lifecycle=Lifecycle.SUPPORTED,
            citations=(_SUPPORTING,),
        ),
        Node(
            id="supervised-replanning",
            kind=NodeKind.PATTERN,
            label="Supervised replanning",
            statement="A model replans while a human approves each consequential action.",
            lifecycle=Lifecycle.PROPOSED,
            citations=(_SUPPORTING,),
        ),
        # Two theories that disagree about the same concept, published together.
        Node(
            id="agency-needs-unpredictable-steps",
            kind=NodeKind.THEORY,
            label="Agency needs unpredictable steps",
            statement="Runtime agency is warranted only when step order cannot be predefined.",
            lifecycle=Lifecycle.SUPPORTED,
            citations=(_SUPPORTING,),
        ),
        Node(
            id="agency-needs-open-tool-choice",
            kind=NodeKind.THEORY,
            label="Agency needs open tool choice",
            statement="Runtime agency is warranted when tool choice cannot be fixed in advance.",
            lifecycle=Lifecycle.CHALLENGED,
            citations=both,
        ),
        Node(
            id="residual-case-coverage",
            kind=NodeKind.DECISION_CRITERION,
            label="Residual case coverage",
            statement="A fixed workflow must be shown insufficient for the residual cases.",
            lifecycle=Lifecycle.SUPPORTED,
            citations=(_SUPPORTING,),
        ),
        Node(
            id="irreversible-action-veto",
            kind=NodeKind.CONSTRAINT,
            label="Irreversible action veto",
            statement="An irreversible consequential action bars unsupervised runtime authority.",
            lifecycle=Lifecycle.SUPPORTED,
            citations=(_SUPPORTING,),
        ),
        Node(
            id="agency-necessity-rule",
            kind=NodeKind.DECISION_RULE,
            label="Agency necessity rule",
            statement="Agentic control survives only when runtime agency is evidenced.",
            lifecycle=Lifecycle.SUPPORTED,
            citations=(_SUPPORTING,),
        ),
        Node(
            id="fixed-workflow-sufficed",
            kind=NodeKind.COUNTEREXAMPLE,
            label="Fixed workflow sufficed",
            statement="A synthetic case where a fixed workflow covered every residual case.",
            lifecycle=Lifecycle.SUPPORTED,
            citations=(_CHALLENGING,),
        ),
    ]
    relations = [
        Relation(
            id="pattern-specialises-class",
            kind=RelationKind.SPECIALISES,
            subject_id="supervised-replanning",
            object_id="agentic-control",
            statement="Supervised replanning is a constrained form of agentic control.",
            lifecycle=Lifecycle.SUPPORTED,
            citations=(_SUPPORTING,),
        ),
        Relation(
            id="criterion-applies-to-class",
            kind=RelationKind.APPLIES_TO,
            subject_id="residual-case-coverage",
            object_id="agentic-control",
            statement="Residual case coverage is judged before agentic control survives.",
            lifecycle=Lifecycle.SUPPORTED,
            citations=(_SUPPORTING,),
        ),
        Relation(
            id="veto-constrains-class",
            kind=RelationKind.CONSTRAINS,
            subject_id="irreversible-action-veto",
            object_id="agentic-control",
            statement="The veto bars agentic control over irreversible actions.",
            lifecycle=Lifecycle.SUPPORTED,
            citations=(_SUPPORTING,),
        ),
        Relation(
            id="theory-informs-rule",
            kind=RelationKind.INFORMS_RULE,
            subject_id="agency-needs-unpredictable-steps",
            object_id="agency-necessity-rule",
            statement="The theory is the rationale the rule encodes.",
            lifecycle=Lifecycle.SUPPORTED,
            citations=(_SUPPORTING,),
        ),
        Relation(
            id="counterexample-challenges-theory",
            kind=RelationKind.CHALLENGES,
            subject_id="fixed-workflow-sufficed",
            object_id="agency-needs-open-tool-choice",
            statement="The counterexample shows open tool choice alone did not require agency.",
            lifecycle=Lifecycle.SUPPORTED,
            citations=(_CHALLENGING,),
        ),
        Relation(
            id="theory-supports-criterion",
            kind=RelationKind.SUPPORTS,
            subject_id="agency-needs-unpredictable-steps",
            object_id="residual-case-coverage",
            statement="The theory motivates judging residual coverage first.",
            lifecycle=Lifecycle.SUPPORTED,
            citations=(_SUPPORTING,),
        ),
        Relation(
            id="theory-supersedes-theory",
            kind=RelationKind.SUPERSEDES,
            subject_id="agency-needs-unpredictable-steps",
            object_id="agency-needs-open-tool-choice",
            statement="The step-order theory supersedes the tool-choice theory by reference.",
            lifecycle=Lifecycle.PROPOSED,
            citations=(_SUPPORTING,),
        ),
    ]
    return nodes, relations


def _snapshot() -> Any:
    nodes, relations = _knowledge()
    return build_snapshot(nodes, relations)


def test_snapshot_matches_its_exact_golden_and_covers_every_node_kind() -> None:
    snapshot = _snapshot()
    content = canonical_snapshot_bytes(snapshot)

    assert content == _GOLDEN.read_bytes()
    assert content.endswith(b"\n") and not content.endswith(b"\n\n")
    assert b"\r" not in content
    assert {node.kind for node in snapshot.nodes} == set(NodeKind)
    assert {relation.kind for relation in snapshot.relations} == set(RelationKind)
    stances = {citation.stance for node in snapshot.nodes for citation in node.citations}
    assert stances == set(Stance)


def test_golden_snapshot_is_pinned_to_lf_line_endings() -> None:
    attributes = (Path(__file__).parent.parent / ".gitattributes").read_text(encoding="utf-8")

    assert "tests/golden/*.json text eol=lf" in attributes


def test_identical_knowledge_in_any_order_produces_identical_bytes() -> None:
    nodes, relations = _knowledge()
    first = build_snapshot(nodes, relations)
    second = build_snapshot(list(reversed(nodes)), list(reversed(relations)))

    assert canonical_snapshot_bytes(second) == canonical_snapshot_bytes(first)
    assert second.graph_version == first.graph_version
    assert second.snapshot_content_identity == first.snapshot_content_identity
    assert [node.id for node in second.nodes] == [node.id for node in first.nodes]
    assert [item.id for item in second.relations] == [item.id for item in first.relations]


def test_the_immutable_graph_version_describes_the_knowledge_and_is_hashed_with_it() -> None:
    nodes, relations = _knowledge()
    snapshot = build_snapshot(nodes, relations)
    payload = canonical_snapshot_dict(snapshot)

    assert snapshot.graph_version == immutable_graph_version(nodes, relations)
    assert snapshot.graph_version.startswith("gv1:")
    # Inside the hashed payload: removing only the identity field leaves it.
    hashed = {key: value for key, value in payload.items() if key != "snapshot_content_identity"}
    assert "graph_version" in hashed
    assert snapshot.snapshot_content_identity == (
        f"sha256:{sha256(canonical_json_bytes(hashed)).hexdigest()}"
    )


def test_semantic_identifiers_survive_a_change_to_mutable_content() -> None:
    nodes, relations = _knowledge()
    original = build_snapshot(nodes, relations)
    changed = [
        replace(node, lifecycle=Lifecycle.DEPRECATED) if node.id == "runtime-agency" else node
        for node in nodes
    ]

    revised = build_snapshot(changed, relations)

    assert [node.id for node in revised.nodes] == [node.id for node in original.nodes]
    assert [item.id for item in revised.relations] == [item.id for item in original.relations]
    assert revised.graph_version != original.graph_version
    assert revised.snapshot_content_identity != original.snapshot_content_identity


def test_competing_theories_are_published_and_loaded_without_being_merged() -> None:
    snapshot = _snapshot()

    loaded = load_snapshot(canonical_snapshot_bytes(snapshot))

    theories = [node for node in loaded.nodes if node.kind is NodeKind.THEORY]
    assert len(theories) == 2
    assert {node.lifecycle for node in theories} == {Lifecycle.SUPPORTED, Lifecycle.CHALLENGED}
    assert len({node.statement for node in theories}) == 2
    # The conflict itself is visible as a published relation, not resolved away.
    challenge = next(item for item in loaded.relations if item.kind is RelationKind.CHALLENGES)
    assert challenge.object_id == "agency-needs-open-tool-choice"
    supersession = next(item for item in loaded.relations if item.kind is RelationKind.SUPERSEDES)
    assert supersession.object_id == "agency-needs-open-tool-choice"
    assert loaded == snapshot


def test_a_published_snapshot_round_trips_through_its_own_bytes() -> None:
    snapshot = _snapshot()
    content = canonical_snapshot_bytes(snapshot)

    loaded = load_snapshot(content)

    assert loaded == snapshot
    assert canonical_snapshot_bytes(loaded) == content
    assert snapshot_reference(loaded) == {
        "graph_schema_version": GRAPH_SCHEMA_VERSION,
        "graph_snapshot_content_identity": snapshot.snapshot_content_identity,
        "graph_version": snapshot.graph_version,
    }


def test_a_citation_may_bind_retained_bytes_or_leave_them_unarchived() -> None:
    nodes, relations = _knowledge()
    identity = f"sha256:{'a' * 64}"
    bound = [
        replace(node, citations=(replace(node.citations[0], content_identity=identity),))
        if node.id == "runtime-agency"
        else node
        for node in nodes
    ]

    snapshot = build_snapshot(bound, relations)

    concept = next(node for node in snapshot.nodes if node.id == "runtime-agency")
    assert concept.citations[0].content_identity == identity
    unarchived = next(node for node in snapshot.nodes if node.id == "agentic-control")
    assert unarchived.citations[0].content_identity is None
    assert load_snapshot(canonical_snapshot_bytes(snapshot)) == snapshot


def test_canonical_bytes_carry_no_run_variant_metadata() -> None:
    content = canonical_snapshot_bytes(_snapshot())
    payload = json.loads(content)

    assert list(payload) == sorted(payload)
    assert set(payload) == {
        "graph_schema_version",
        "graph_version",
        "nodes",
        "relations",
        "snapshot_content_identity",
    }
    for forbidden in (b"generated_at", b"timestamp", b"created", b"/Users/", b"C:\\\\"):
        assert forbidden not in content, forbidden


def test_building_and_loading_never_touch_the_filesystem_or_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A locator is provenance data: nothing dereferences, opens, or fetches it."""
    snapshot = _snapshot()
    content = canonical_snapshot_bytes(snapshot)
    # Warm the packaged schema before the guards, so the check covers the
    # snapshot path rather than one-time resource loading.
    load_snapshot(content)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("snapshot handling dereferenced a locator")

    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)

    nodes, relations = _knowledge()
    assert canonical_snapshot_bytes(build_snapshot(nodes, relations)) == content
    assert load_snapshot(content) == snapshot


def test_the_schema_cannot_express_case_scoped_material() -> None:
    raw = json.loads(
        (
            Path(__file__).parent.parent
            / "src"
            / "archsift"
            / "schemas"
            / "graph-snapshot-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    kinds = set(raw["$defs"]["node"]["properties"]["kind"]["enum"])

    assert kinds == {kind.value for kind in NodeKind}
    for case_scoped in ("case", "dossier", "candidate", "task", "verdict", "finding"):
        assert not any(case_scoped in kind for kind in kinds), case_scoped
    assert raw["additionalProperties"] is False
    assert raw["$defs"]["node"]["additionalProperties"] is False
    assert raw["$defs"]["relation"]["additionalProperties"] is False


def _tampered(mutate: Any) -> bytes:
    payload = cast(dict[str, Any], json.loads(canonical_snapshot_bytes(_snapshot())))
    mutate(payload)
    return canonical_json_bytes(payload)


@pytest.mark.parametrize(
    ("mutate", "category", "exit_code"),
    [
        (
            lambda payload: payload.__setitem__("graph_schema_version", 99),
            SnapshotFailure.UNSUPPORTED_SCHEMA,
            ExitCode.UNSUPPORTED_SCHEMA,
        ),
        (
            lambda payload: payload["nodes"][0].__setitem__("kind", "case-dossier"),
            SnapshotFailure.MALFORMED_SNAPSHOT,
            ExitCode.VALIDATION_FAILED,
        ),
        (
            lambda payload: payload["relations"][0].__setitem__("kind", "relates-somehow"),
            SnapshotFailure.MALFORMED_SNAPSHOT,
            ExitCode.VALIDATION_FAILED,
        ),
        (
            lambda payload: payload["nodes"][0].__setitem__("unexpected", "value"),
            SnapshotFailure.MALFORMED_SNAPSHOT,
            ExitCode.VALIDATION_FAILED,
        ),
        (
            lambda payload: payload["nodes"][0].pop("lifecycle"),
            SnapshotFailure.MALFORMED_SNAPSHOT,
            ExitCode.VALIDATION_FAILED,
        ),
        (
            lambda payload: payload.__setitem__("graph_version", f"gv1:{'0' * 64}"),
            SnapshotFailure.IDENTITY_MISMATCH,
            ExitCode.VALIDATION_FAILED,
        ),
        (
            lambda payload: payload.__setitem__("snapshot_content_identity", f"sha256:{'0' * 64}"),
            SnapshotFailure.IDENTITY_MISMATCH,
            ExitCode.VALIDATION_FAILED,
        ),
    ],
)
def test_a_tampered_snapshot_fails_closed(
    mutate: Any, category: SnapshotFailure, exit_code: ExitCode
) -> None:
    with pytest.raises(SnapshotError) as failure:
        load_snapshot(_tampered(mutate))

    assert failure.value.category is category
    assert failure.value.exit_code is exit_code
    assert failure.value.to_dict()["requirement"] == "FR-015"
    assert failure.value.remediation


def test_non_canonical_bytes_are_refused_even_when_the_content_is_valid() -> None:
    payload = json.loads(canonical_snapshot_bytes(_snapshot()))
    spaced = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")

    with pytest.raises(SnapshotError) as failure:
        load_snapshot(spaced)

    assert failure.value.category is SnapshotFailure.MALFORMED_SNAPSHOT


@pytest.mark.parametrize(
    ("content", "category", "exit_code"),
    [
        (b"\xff\xfe not utf-8", SnapshotFailure.INVALID_UTF8, ExitCode.MALFORMED_INPUT),
        (b"{not json}\n", SnapshotFailure.INVALID_JSON, ExitCode.MALFORMED_INPUT),
        (b"[]\n", SnapshotFailure.MALFORMED_SNAPSHOT, ExitCode.VALIDATION_FAILED),
        (b'{"a":NaN}\n', SnapshotFailure.INVALID_JSON, ExitCode.MALFORMED_INPUT),
        (
            b'{"graph_schema_version":1,"graph_schema_version":1}\n',
            SnapshotFailure.INVALID_JSON,
            ExitCode.MALFORMED_INPUT,
        ),
    ],
)
def test_unreadable_input_is_classified_rather_than_crashing(
    content: bytes, category: SnapshotFailure, exit_code: ExitCode
) -> None:
    with pytest.raises(SnapshotError) as failure:
        load_snapshot(content)

    assert failure.value.category is category
    assert failure.value.exit_code is exit_code


def test_an_assertion_without_provenance_is_refused() -> None:
    nodes, relations = _knowledge()
    stripped = [
        replace(node, citations=()) if node.id == "runtime-agency" else node for node in nodes
    ]

    with pytest.raises(SnapshotError) as failure:
        build_snapshot(stripped, relations)

    assert failure.value.category is SnapshotFailure.MISSING_PROVENANCE
    assert "runtime-agency" in failure.value.message


def test_a_relation_without_provenance_is_refused() -> None:
    nodes, relations = _knowledge()
    stripped = [replace(relations[0], citations=()), *relations[1:]]

    with pytest.raises(SnapshotError) as failure:
        build_snapshot(nodes, stripped)

    assert failure.value.category is SnapshotFailure.MISSING_PROVENANCE


def test_an_evidence_source_without_a_source_is_refused() -> None:
    nodes, relations = _knowledge()
    stripped = [replace(node, source=None) if node.source is not None else node for node in nodes]

    with pytest.raises(SnapshotError) as failure:
        build_snapshot(stripped, relations)

    assert failure.value.category is SnapshotFailure.MISSING_PROVENANCE


def test_an_assertion_may_not_masquerade_as_its_own_source() -> None:
    nodes, relations = _knowledge()
    forged = [
        replace(
            node,
            source=Source(
                locator="urn:example:self",
                date_kind=DateKind.OBSERVED,
                dated=date(2026, 1, 1),
            ),
        )
        if node.id == "runtime-agency"
        else node
        for node in nodes
    ]

    with pytest.raises(SnapshotError, match="records a source of its own"):
        build_snapshot(forged, relations)


def test_a_relation_outside_its_declared_semantics_is_refused() -> None:
    nodes, relations = _knowledge()
    undefined = [
        *relations,
        Relation(
            id="source-constrains-class",
            kind=RelationKind.CONSTRAINS,
            subject_id="source-primary",
            object_id="agentic-control",
            statement="An evidence source cannot constrain a class.",
            lifecycle=Lifecycle.PROPOSED,
            citations=(_SUPPORTING,),
        ),
    ]

    with pytest.raises(SnapshotError) as failure:
        build_snapshot(nodes, undefined)

    assert failure.value.category is SnapshotFailure.UNDEFINED_RELATION
    assert "constrains" in failure.value.message


def test_a_relation_to_an_unknown_node_is_refused() -> None:
    nodes, relations = _knowledge()
    dangling = [replace(relations[0], object_id="never-declared"), *relations[1:]]

    with pytest.raises(SnapshotError) as failure:
        build_snapshot(nodes, dangling)

    assert failure.value.category is SnapshotFailure.DANGLING_REFERENCE


def test_a_citation_of_an_unknown_source_is_refused() -> None:
    nodes, relations = _knowledge()
    dangling = [
        replace(node, citations=(Citation(source_id="absent", stance=Stance.SUPPORTS),))
        if node.id == "runtime-agency"
        else node
        for node in nodes
    ]

    with pytest.raises(SnapshotError) as failure:
        build_snapshot(dangling, relations)

    assert failure.value.category is SnapshotFailure.DANGLING_REFERENCE


def test_a_malformed_cited_content_identity_is_refused() -> None:
    nodes, relations = _knowledge()
    bad = [
        replace(node, citations=(replace(node.citations[0], content_identity="sha256:nope"),))
        if node.id == "runtime-agency"
        else node
        for node in nodes
    ]

    with pytest.raises(SnapshotError, match="malformed cited-content identity"):
        build_snapshot(bad, relations)


def test_duplicate_semantic_identifiers_are_refused() -> None:
    nodes, relations = _knowledge()

    with pytest.raises(SnapshotError) as node_failure:
        build_snapshot([*nodes, nodes[2]], relations)
    with pytest.raises(SnapshotError) as relation_failure:
        build_snapshot(nodes, [*relations, relations[0]])

    assert node_failure.value.category is SnapshotFailure.DUPLICATE_IDENTIFIER
    assert relation_failure.value.category is SnapshotFailure.DUPLICATE_IDENTIFIER


def test_a_relation_from_a_node_to_itself_is_refused() -> None:
    nodes, relations = _knowledge()
    reflexive = [
        replace(relations[0], subject_id="agentic-control", object_id="agentic-control"),
        *relations[1:],
    ]

    with pytest.raises(SnapshotError, match="to itself"):
        build_snapshot(nodes, reflexive)


def test_snapshot_bytes_are_hash_seed_independent() -> None:
    script = f"""
import sys
sys.path.insert(0, {str(Path(__file__).parent)!r})
from archsift.knowledge_graph import build_snapshot, canonical_snapshot_bytes
from test_knowledge_graph import _knowledge
nodes, relations = _knowledge()
print(canonical_snapshot_bytes(build_snapshot(nodes, relations)).hex())
"""
    outputs = []
    for seed in ("1", "947"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        outputs.append(
            subprocess.run(
                [sys.executable, "-c", script],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            ).stdout
        )
    assert outputs[0] == outputs[1]


def test_case_view_traces_reusable_claims_to_private_findings_and_surfaces_conflict() -> None:
    snapshot = _snapshot()
    request = CaseViewRequest(
        root_ids=("runtime-agency",),
        finding_ids=("finding-agency",),
        bindings=(FindingBinding("finding-agency", "agency-necessity-rule"),),
    )

    view = construct_case_view(snapshot, request)

    assert view.content["graph_version"] == snapshot.graph_version
    traces = cast(list[dict[str, Any]], view.content["reusable_claim_traces"])
    trace = next(item for item in traces if item["claim_id"] == "agency-needs-unpredictable-steps")
    assert trace["case_finding_ids"] == ["finding-agency"]
    assert trace["citations"] == [{"source_id": "source-primary", "stance": "supports"}]
    assert "counterexample-challenges-theory" in cast(
        list[str], view.content["conflict_relation_ids"]
    )
    assert "fixed-workflow-sufficed" in cast(
        list[str], view.content["reusable_knowledge_gap_claim_ids"]
    )


def test_case_view_is_order_independent_and_does_not_mutate_the_snapshot() -> None:
    snapshot = _snapshot()
    first = CaseViewRequest(
        root_ids=("agentic-control", "runtime-agency"),
        finding_ids=("finding-agency",),
        bindings=(FindingBinding("finding-agency", "agency-necessity-rule"),),
    )
    second = replace(first, root_ids=tuple(reversed(first.root_ids)))
    before = canonical_snapshot_bytes(snapshot)

    assert construct_case_view(snapshot, first) == construct_case_view(snapshot, second)
    assert canonical_snapshot_bytes(snapshot) == before


def test_case_view_refuses_unknown_and_non_rule_bindings() -> None:
    snapshot = _snapshot()
    with pytest.raises(CaseViewError, match="not in the published snapshot"):
        construct_case_view(snapshot, CaseViewRequest(("absent",), (), ()))
    with pytest.raises(CaseViewError, match="not a decision rule"):
        construct_case_view(
            snapshot,
            CaseViewRequest(
                ("runtime-agency",),
                ("finding",),
                (FindingBinding("finding", "runtime-agency"),),
            ),
        )
