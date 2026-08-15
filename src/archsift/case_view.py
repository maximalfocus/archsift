"""Deterministic private case views over one published knowledge snapshot."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import cast

from archsift.canonical import JsonObject, canonical_json_bytes
from archsift.knowledge_graph import NodeKind, Relation, RelationKind, Snapshot

_TRAVERSABLE = frozenset(
    {
        RelationKind.APPLIES_TO,
        RelationKind.SUPPORTS,
        RelationKind.CHALLENGES,
        RelationKind.SUPERSEDES,
        RelationKind.INFORMS_RULE,
    }
)


class CaseViewFailure(StrEnum):
    UNKNOWN_ROOT = "unknown-root"
    UNKNOWN_FINDING = "unknown-finding"
    UNKNOWN_RULE = "unknown-rule"
    NON_RULE_BINDING = "non-rule-binding"
    DUPLICATE_BINDING = "duplicate-binding"
    CONTRADICTORY_BINDING = "contradictory-binding"


class CaseViewError(ValueError):
    def __init__(
        self, category: CaseViewFailure, field: str, message: str, remediation: str
    ) -> None:
        self.category = category
        self.field = field
        self.message = message
        self.remediation = remediation
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class FindingBinding:
    finding_id: str
    rule_id: str


@dataclass(frozen=True, slots=True)
class CaseViewRequest:
    root_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    bindings: tuple[FindingBinding, ...]


@dataclass(frozen=True, slots=True)
class CaseKnowledgeView:
    content: JsonObject
    content_identity: str


def _fail(category: CaseViewFailure, field: str, message: str, remediation: str) -> CaseViewError:
    return CaseViewError(category, field, message, remediation)


def _validate_request(snapshot: Snapshot, request: CaseViewRequest) -> dict[str, tuple[str, ...]]:
    nodes = {node.id: node for node in snapshot.nodes}
    for root in request.root_ids:
        if root not in nodes:
            raise _fail(
                CaseViewFailure.UNKNOWN_ROOT,
                "$.root_ids",
                f"Case-view root {root!r} is not in the published snapshot.",
                "Name only stable semantic identifiers declared by this snapshot.",
            )
    if len(set(request.finding_ids)) != len(request.finding_ids):
        raise _fail(
            CaseViewFailure.UNKNOWN_FINDING,
            "$.finding_ids",
            "The case-view request repeats a case finding identifier.",
            "Declare each private case finding exactly once.",
        )
    seen: set[tuple[str, str]] = set()
    by_finding: dict[str, set[str]] = {}
    for binding in request.bindings:
        pair = (binding.finding_id, binding.rule_id)
        if pair in seen:
            raise _fail(
                CaseViewFailure.DUPLICATE_BINDING,
                "$.bindings",
                f"Binding {pair!r} is declared more than once.",
                "Declare each finding-to-rule binding once.",
            )
        seen.add(pair)
        if binding.finding_id not in request.finding_ids:
            raise _fail(
                CaseViewFailure.UNKNOWN_FINDING,
                "$.bindings[].finding_id",
                f"Binding names undeclared case finding {binding.finding_id!r}.",
                "Declare the private finding before binding it to a reusable rule.",
            )
        rule = nodes.get(binding.rule_id)
        if rule is None:
            raise _fail(
                CaseViewFailure.UNKNOWN_RULE,
                "$.bindings[].rule_id",
                f"Binding names unknown reusable rule {binding.rule_id!r}.",
                "Bind only a decision-rule identifier declared by this snapshot.",
            )
        if rule.kind is not NodeKind.DECISION_RULE:
            raise _fail(
                CaseViewFailure.NON_RULE_BINDING,
                "$.bindings[].rule_id",
                f"Node {binding.rule_id!r} is not a decision rule.",
                "Bind the finding to a node whose kind is decision-rule.",
            )
        by_finding.setdefault(binding.finding_id, set()).add(binding.rule_id)
    contradictory = next((key for key, values in by_finding.items() if len(values) > 1), None)
    if contradictory is not None:
        raise _fail(
            CaseViewFailure.CONTRADICTORY_BINDING,
            "$.bindings",
            f"Case finding {contradictory!r} is bound to more than one reusable rule.",
            "Give each case finding one explicit reusable-rule binding.",
        )
    return {
        rule: tuple(
            sorted(binding.finding_id for binding in request.bindings if binding.rule_id == rule)
        )
        for rule in sorted({binding.rule_id for binding in request.bindings})
    }


def _relevant(snapshot: Snapshot, roots: tuple[str, ...], rules: set[str]) -> set[str]:
    relevant = set(roots) | rules
    changed = True
    while changed:
        changed = False
        for relation in snapshot.relations:
            if relation.kind not in _TRAVERSABLE:
                continue
            if relation.subject_id in relevant or relation.object_id in relevant:
                before = len(relevant)
                relevant.update((relation.subject_id, relation.object_id))
                changed |= len(relevant) != before
    return relevant


def _rule_paths(claim: str, rules: set[str], relations: tuple[Relation, ...]) -> list[list[str]]:
    edges: dict[str, list[tuple[str, str]]] = {}
    for relation in relations:
        if relation.kind in _TRAVERSABLE:
            edges.setdefault(relation.subject_id, []).append((relation.id, relation.object_id))
    queue = deque([(claim, [claim])])
    visited = {claim}
    found: list[list[str]] = []
    while queue:
        current, path = queue.popleft()
        if current in rules and current != claim:
            found.append(path)
            continue
        for relation_id, target in sorted(edges.get(current, ())):
            if target not in visited:
                visited.add(target)
                queue.append((target, [*path, relation_id, target]))
    return sorted(found)


def construct_case_view(snapshot: Snapshot, request: CaseViewRequest) -> CaseKnowledgeView:
    """Construct a private explainability view without changing case judgment."""
    findings_by_rule = _validate_request(snapshot, request)
    rules = set(findings_by_rule)
    relevant = _relevant(snapshot, request.root_ids, rules)
    relations = tuple(
        relation
        for relation in snapshot.relations
        if relation.subject_id in relevant and relation.object_id in relevant
    )
    traces: list[JsonObject] = []
    gaps: list[str] = []
    for node in snapshot.nodes:
        if node.id not in relevant or node.kind in {
            NodeKind.EVIDENCE_SOURCE,
            NodeKind.DECISION_RULE,
        }:
            continue
        paths = _rule_paths(node.id, rules, relations)
        reached = sorted({path[-1] for path in paths})
        case_findings = sorted({item for rule in reached for item in findings_by_rule[rule]})
        if not case_findings:
            gaps.append(node.id)
        traces.append(
            cast(
                JsonObject,
                {
                    "case_finding_ids": case_findings,
                    "claim_id": node.id,
                    "citations": [
                        {"source_id": item.source_id, "stance": item.stance.value}
                        for item in node.citations
                    ],
                    "lifecycle": node.lifecycle.value,
                    "rule_paths": paths,
                },
            )
        )
    conflicts = [
        relation.id
        for relation in relations
        if relation.kind in {RelationKind.CHALLENGES, RelationKind.SUPERSEDES}
    ]
    content = cast(
        JsonObject,
        {
            "case_finding_ids": sorted(request.finding_ids),
            "conflict_relation_ids": sorted(conflicts),
            "graph_schema_version": snapshot.graph_schema_version,
            "graph_snapshot_content_identity": snapshot.snapshot_content_identity,
            "graph_version": snapshot.graph_version,
            "relevance_root_ids": sorted(set(request.root_ids)),
            "reusable_claim_traces": sorted(traces, key=lambda item: str(item["claim_id"])),
            "reusable_knowledge_gap_claim_ids": sorted(gaps),
        },
    )
    identity = f"sha256:{sha256(canonical_json_bytes(content)).hexdigest()}"
    return CaseKnowledgeView(content=content, content_identity=identity)
