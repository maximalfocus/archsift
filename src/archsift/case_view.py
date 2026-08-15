"""Deterministic private case views over one published knowledge snapshot."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any, Final, cast

from archsift.canonical import JsonObject, canonical_json_bytes
from archsift.diagnostics import ExitCode
from archsift.knowledge_graph import (
    NodeKind,
    Relation,
    RelationKind,
    Snapshot,
    node_content_identity,
    relation_content_identity,
)

_TRAVERSABLE = frozenset(
    {
        RelationKind.APPLIES_TO,
        RelationKind.SUPPORTS,
        RelationKind.CHALLENGES,
        RelationKind.SUPERSEDES,
        RelationKind.INFORMS_RULE,
    }
)
CASE_VIEW_REQUEST_SCHEMA_VERSION: Final = 1


class CaseViewFailure(StrEnum):
    INVALID_UTF8 = "invalid-utf8"
    INVALID_JSON = "invalid-json"
    UNSUPPORTED_SCHEMA = "unsupported-schema"
    MALFORMED_REQUEST = "malformed-request"
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

    @property
    def exit_code(self) -> ExitCode:
        if self.category is CaseViewFailure.UNSUPPORTED_SCHEMA:
            return ExitCode.UNSUPPORTED_SCHEMA
        if self.category in {CaseViewFailure.INVALID_UTF8, CaseViewFailure.INVALID_JSON}:
            return ExitCode.MALFORMED_INPUT
        return ExitCode.VALIDATION_FAILED


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


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _fail(
                CaseViewFailure.INVALID_JSON,
                "$",
                f"The case-view request repeats JSON field {key!r}.",
                "Emit each request field exactly once.",
            )
        value[key] = item
    return value


def load_case_view_request(content: bytes) -> CaseViewRequest:
    """Load one strict canonical versioned private case-view request."""
    try:
        text = content.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise _fail(
            CaseViewFailure.INVALID_UTF8,
            "$",
            "The case-view request is not valid UTF-8.",
            "Encode the canonical JSON request as UTF-8.",
        ) from error
    try:
        raw = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except CaseViewError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise _fail(
            CaseViewFailure.INVALID_JSON,
            "$",
            "The case-view request is not unambiguous JSON.",
            "Provide one canonical JSON object without duplicate fields or non-standard numbers.",
        ) from error
    if type(raw) is not dict:
        raise _fail(
            CaseViewFailure.MALFORMED_REQUEST,
            "$",
            "The case-view request root is not an object.",
            "Provide the versioned request object.",
        )
    request = cast(dict[str, Any], raw)
    declared = request.get("request_schema_version")
    if type(declared) is int and declared != CASE_VIEW_REQUEST_SCHEMA_VERSION:
        raise _fail(
            CaseViewFailure.UNSUPPORTED_SCHEMA,
            "$.request_schema_version",
            f"Case-view request schema version {declared} is not supported.",
            f"Use request schema version {CASE_VIEW_REQUEST_SCHEMA_VERSION} or upgrade ArchSift.",
        )
    if set(request) != {"bindings", "finding_ids", "request_schema_version", "root_ids"}:
        raise _fail(
            CaseViewFailure.MALFORMED_REQUEST,
            "$",
            "The case-view request has an unsupported field contract.",
            "Provide only request_schema_version, root_ids, finding_ids, and bindings.",
        )
    try:
        roots = request["root_ids"]
        findings = request["finding_ids"]
        raw_bindings = request["bindings"]
        if (
            declared != CASE_VIEW_REQUEST_SCHEMA_VERSION
            or type(roots) is not list
            or type(findings) is not list
            or type(raw_bindings) is not list
            or not all(type(item) is str and item for item in [*roots, *findings])
        ):
            raise ValueError
        bindings: list[FindingBinding] = []
        for item in raw_bindings:
            if type(item) is not dict or set(item) != {"finding_id", "rule_id"}:
                raise ValueError
            finding_id = item["finding_id"]
            rule_id = item["rule_id"]
            if (
                type(finding_id) is not str
                or not finding_id
                or type(rule_id) is not str
                or not rule_id
            ):
                raise ValueError
            bindings.append(FindingBinding(finding_id, rule_id))
        result = CaseViewRequest(tuple(roots), tuple(findings), tuple(bindings))
    except (KeyError, TypeError, ValueError) as error:
        raise _fail(
            CaseViewFailure.MALFORMED_REQUEST,
            "$",
            "The case-view request does not satisfy schema version 1.",
            "Use non-empty string arrays and binding objects with finding_id and rule_id.",
        ) from error
    if canonical_json_bytes(cast(JsonObject, request)) != content:
        raise _fail(
            CaseViewFailure.MALFORMED_REQUEST,
            "$",
            "The case-view request bytes are not canonical JSON.",
            "Serialize the request with sorted keys, compact separators, UTF-8, and one LF.",
        )
    return result


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
    reached_node_ids: set[str] = set()
    reached_relation_ids: set[str] = set()
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
        else:
            for path in paths:
                if path[-1] in findings_by_rule:
                    reached_node_ids.update(path[::2])
                    reached_relation_ids.update(path[1::2])
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
    node_by_id = {node.id: node for node in snapshot.nodes}
    relation_by_id = {relation.id: relation for relation in snapshot.relations}
    content = cast(
        JsonObject,
        {
            "case_finding_ids": sorted(request.finding_ids),
            "conflict_relation_ids": sorted(conflicts),
            "finding_relevant_nodes": [
                {
                    "content_identity": node_content_identity(node_by_id[identifier]),
                    "id": identifier,
                }
                for identifier in sorted(reached_node_ids)
            ],
            "finding_relevant_relations": [
                {
                    "content_identity": relation_content_identity(relation_by_id[identifier]),
                    "id": identifier,
                }
                for identifier in sorted(reached_relation_ids)
            ],
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
