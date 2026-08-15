"""Evidence-backed governance for immutable knowledge-graph evolution.

FR-014/FR-015: a canonical proposal must account for every semantic entry
delta between exact immutable snapshots. Validation is deterministic,
offline, read-only, and never dereferences an evidence-source locator.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from functools import cache
from importlib.resources import files
from typing import Any, Final, cast

from jsonschema import Draft202012Validator, FormatChecker

from archsift.canonical import JsonObject, canonical_json_bytes
from archsift.diagnostics import ExitCode
from archsift.knowledge_graph import (
    Lifecycle,
    Node,
    NodeKind,
    Relation,
    RelationKind,
    Snapshot,
    node_content_identity,
    relation_content_identity,
    snapshot_reference,
)

GRAPH_CHANGE_SCHEMA_VERSION: Final = 1


class GraphChangeFailure(StrEnum):
    """Stable failure categories at the graph-evolution boundary."""

    INVALID_UTF8 = "invalid-utf8"
    INVALID_JSON = "invalid-json"
    UNSUPPORTED_SCHEMA = "unsupported-schema"
    MALFORMED_PROPOSAL = "malformed-proposal"
    NON_CANONICAL = "non-canonical"
    SNAPSHOT_MISMATCH = "snapshot-mismatch"
    DELTA_MISMATCH = "delta-mismatch"
    INVALID_SEMANTICS = "invalid-semantics"
    EVIDENCE_MISMATCH = "evidence-mismatch"
    BEHAVIOR_PROOF_MISSING = "behavior-proof-missing"


class GraphChangeError(ValueError):
    """One safely classified graph-change proposal failure."""

    def __init__(
        self, category: GraphChangeFailure, field: str, message: str, remediation: str
    ) -> None:
        self.category = category
        self.field = field
        self.message = message
        self.remediation = remediation
        super().__init__(message)

    @property
    def exit_code(self) -> ExitCode:
        """Map a proposal failure to the stable public CLI contract."""
        if self.category is GraphChangeFailure.UNSUPPORTED_SCHEMA:
            return ExitCode.UNSUPPORTED_SCHEMA
        if self.category in {
            GraphChangeFailure.INVALID_UTF8,
            GraphChangeFailure.INVALID_JSON,
        }:
            return ExitCode.MALFORMED_INPUT
        return ExitCode.VALIDATION_FAILED


def _error(
    category: GraphChangeFailure, field: str, message: str, remediation: str
) -> GraphChangeError:
    return GraphChangeError(category, field, message, remediation)


@cache
def _proposal_validator() -> Draft202012Validator:
    raw = json.loads(
        files("archsift")
        .joinpath("schemas/graph-change-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if type(raw) is not dict:
        raise TypeError("packaged graph-change schema must be an object")
    return Draft202012Validator(cast(dict[str, Any], raw), format_checker=FormatChecker())


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _error(
                GraphChangeFailure.INVALID_JSON,
                "$",
                f"The proposal repeats the JSON field {key!r}.",
                "Emit each field exactly once in canonical JSON.",
            )
        result[key] = value
    return result


def load_graph_change_proposal(content: bytes) -> JsonObject:
    """Load one strict, canonical graph-change proposal."""
    try:
        text = content.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise _error(
            GraphChangeFailure.INVALID_UTF8,
            "$",
            "The graph-change proposal is not valid UTF-8.",
            "Replace it with the exact canonical UTF-8 proposal bytes.",
        ) from error
    try:
        loaded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"unsupported JSON constant {value}")
            ),
        )
    except GraphChangeError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise _error(
            GraphChangeFailure.INVALID_JSON,
            "$",
            "The graph-change proposal is not unambiguous JSON.",
            "Replace it with strict canonical JSON.",
        ) from error
    if type(loaded) is not dict:
        raise _error(
            GraphChangeFailure.MALFORMED_PROPOSAL,
            "$",
            "The graph-change proposal root is not an object.",
            "Publish a proposal object satisfying graph-change schema version 1.",
        )
    raw = cast(dict[str, Any], loaded)
    declared = raw.get("change_schema_version")
    if type(declared) is int and declared != GRAPH_CHANGE_SCHEMA_VERSION:
        raise _error(
            GraphChangeFailure.UNSUPPORTED_SCHEMA,
            "$.change_schema_version",
            f"Graph-change schema version {declared!r} is not supported.",
            f"Use version {GRAPH_CHANGE_SCHEMA_VERSION} or upgrade ArchSift.",
        )
    schema_error = next(_proposal_validator().iter_errors(raw), None)
    if schema_error is not None:
        field = "$" + "".join(
            f".{part}" if type(part) is str else "[]" for part in schema_error.path
        )
        raise _error(
            GraphChangeFailure.MALFORMED_PROPOSAL,
            field,
            "The proposal does not satisfy graph-change schema version 1.",
            f"Correct {field}: {schema_error.message}",
        )
    proposal = cast(JsonObject, raw)
    if canonical_json_bytes(proposal) != content:
        raise _error(
            GraphChangeFailure.NON_CANONICAL,
            "$",
            "The proposal bytes are not their canonical serialization.",
            "Sort object keys and arrays as required, use compact JSON, and end with one LF.",
        )
    return proposal


def _strings(value: object) -> list[str]:
    return [cast(str, item) for item in cast(list[object], value)]


def _entry_sources(entry: Node | Relation) -> list[str]:
    if isinstance(entry, Node) and entry.kind is NodeKind.EVIDENCE_SOURCE:
        return [entry.id]
    return sorted(citation.source_id for citation in entry.citations)


def _entry_lifecycle(entry: Node | Relation) -> Lifecycle:
    return entry.lifecycle


def _entry_kind(entry: Node | Relation) -> str:
    return "node" if isinstance(entry, Node) else "relation"


def _content_identity(entry: Node | Relation) -> str:
    if isinstance(entry, Node):
        return node_content_identity(entry)
    return relation_content_identity(entry)


def _entries(snapshot: Snapshot | None) -> dict[tuple[str, str], Node | Relation]:
    if snapshot is None:
        return {}
    result: dict[tuple[str, str], Node | Relation] = {}
    result.update({("node", item.id): item for item in snapshot.nodes})
    result.update({("relation", item.id): item for item in snapshot.relations})
    return result


def _actual_delta(
    base: Snapshot | None, proposed: Snapshot
) -> tuple[list[tuple[str, str, str]], dict[tuple[str, str], Node | Relation]]:
    old = _entries(base)
    new = _entries(proposed)
    keys = sorted(set(old) | set(new))
    changes: list[tuple[str, str, str]] = []
    for key in keys:
        if key not in old:
            changes.append((*key, "added"))
        elif key not in new:
            changes.append((*key, "removed"))
        elif _content_identity(old[key]) != _content_identity(new[key]):
            changes.append((*key, "changed"))
    return changes, {**old, **new}


def _proposal_changes(proposal: JsonObject) -> list[Mapping[str, Any]]:
    return [cast(Mapping[str, Any], item) for item in cast(list[object], proposal["changes"])]


def _validate_order_and_proofs(proposal: JsonObject) -> None:
    changes = _proposal_changes(proposal)
    keys = [(str(item["entry_kind"]), str(item["id"])) for item in changes]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise _error(
            GraphChangeFailure.MALFORMED_PROPOSAL,
            "$.changes",
            "Changed entries are not a unique canonical stable-ID list.",
            "Sort changes by entry_kind then id and declare each entry exactly once.",
        )
    for index, item in enumerate(changes):
        sources = _strings(item["evidence_source_ids"])
        if sources != sorted(sources) or len(sources) != len(set(sources)):
            raise _error(
                GraphChangeFailure.MALFORMED_PROPOSAL,
                f"$.changes[{index}].evidence_source_ids",
                "Evidence-source IDs are not a unique canonical list.",
                "Sort the IDs and declare each evidence source exactly once.",
            )
    counterexamples = _strings(proposal["synthetic_counterexample_ids"])
    regressions = _strings(proposal["regression_test_ids"])
    for field, values in (
        ("synthetic_counterexample_ids", counterexamples),
        ("regression_test_ids", regressions),
    ):
        if values != sorted(values) or len(values) != len(set(values)):
            raise _error(
                GraphChangeFailure.MALFORMED_PROPOSAL,
                f"$.{field}",
                f"{field.replace('_', ' ').capitalize()} are not a unique canonical list.",
                "Sort the IDs and declare each structural reference exactly once.",
            )
    behavior_change = cast(bool, proposal["behavior_change"])
    if behavior_change != bool(counterexamples and regressions) or (
        not behavior_change and (counterexamples or regressions)
    ):
        raise _error(
            GraphChangeFailure.BEHAVIOR_PROOF_MISSING,
            "$.behavior_change",
            "The behavior-change declaration and its synthetic proof IDs disagree.",
            "For a behavior change provide both lists; otherwise leave both lists empty.",
        )


def _validate_references(proposal: JsonObject, proposed: Snapshot, base: Snapshot | None) -> None:
    kind = cast(str, proposal["change_kind"])
    proposal_base = proposal["base_snapshot"]
    if kind == "initial-publication":
        if base is not None or proposal_base is not None:
            raise _error(
                GraphChangeFailure.SNAPSHOT_MISMATCH,
                "$.base_snapshot",
                "Initial publication must not name or supply a base snapshot.",
                "Set base_snapshot to null and omit --base-snapshot.",
            )
    elif base is None or proposal_base is None:
        raise _error(
            GraphChangeFailure.SNAPSHOT_MISMATCH,
            "$.base_snapshot",
            "Graph evolution requires an exact immutable base snapshot.",
            "Name the base in the proposal and supply it with --base-snapshot.",
        )
    if proposal["proposed_snapshot"] != snapshot_reference(proposed):
        raise _error(
            GraphChangeFailure.SNAPSHOT_MISMATCH,
            "$.proposed_snapshot",
            "The proposed snapshot reference does not identify the supplied snapshot.",
            "Copy the supplied snapshot's exact schema, graph version, and content identity.",
        )
    if base is not None and proposal_base != snapshot_reference(base):
        raise _error(
            GraphChangeFailure.SNAPSHOT_MISMATCH,
            "$.base_snapshot",
            "The base snapshot reference does not identify the supplied snapshot.",
            "Copy the supplied base snapshot's exact schema, graph version, and identity.",
        )


def _validate_change_semantics(
    proposal: JsonObject, proposed: Snapshot, base: Snapshot | None
) -> list[tuple[str, str, str]]:
    actual, entries = _actual_delta(base, proposed)
    declared = [
        (str(item["entry_kind"]), str(item["id"]), str(item["delta"]))
        for item in _proposal_changes(proposal)
    ]
    if declared != actual:
        raise _error(
            GraphChangeFailure.DELTA_MISMATCH,
            "$.changes",
            "The proposal does not exactly reconstruct the stable semantic entry delta.",
            "Declare every and only added, content-changed, or removed stable entry ID.",
        )
    if proposal["change_kind"] == "initial-publication" and any(
        delta != "added" for _, _, delta in actual
    ):
        raise _error(
            GraphChangeFailure.INVALID_SEMANTICS,
            "$.changes",
            "Initial publication may contain additions only.",
            "Remove the base and describe every proposed entry as an addition.",
        )

    source_ids = {
        node.id
        for snapshot in (base, proposed)
        if snapshot is not None
        for node in snapshot.nodes
        if node.kind is NodeKind.EVIDENCE_SOURCE
    }
    proposed_entries = _entries(proposed)
    for index, item in enumerate(_proposal_changes(proposal)):
        key = (str(item["entry_kind"]), str(item["id"]))
        delta = str(item["delta"])
        rationale = str(item["rationale"])
        declared_sources = _strings(item["evidence_source_ids"])
        if not set(declared_sources).issubset(source_ids):
            raise _error(
                GraphChangeFailure.EVIDENCE_MISMATCH,
                f"$.changes[{index}].evidence_source_ids",
                "A declared evidence-source ID does not resolve in either exact snapshot.",
                "Reference only evidence-source nodes in the base or proposed snapshot.",
            )
        entry = entries[key]
        if delta != "removed" and declared_sources != _entry_sources(proposed_entries[key]):
            raise _error(
                GraphChangeFailure.EVIDENCE_MISMATCH,
                f"$.changes[{index}].evidence_source_ids",
                "The changed proposed entry does not cite exactly its declared evidence sources.",
                "Make the proposal IDs match the entry citations, or its own evidence-source ID.",
            )
        if delta == "removed" and rationale != "removal":
            raise _error(
                GraphChangeFailure.INVALID_SEMANTICS,
                f"$.changes[{index}].rationale",
                "A removed entry must use the removal rationale.",
                "Use rationale removal for an actual removed stable entry.",
            )
        if rationale == "removal" and delta != "removed":
            raise _error(
                GraphChangeFailure.INVALID_SEMANTICS,
                f"$.changes[{index}].rationale",
                "The removal rationale does not describe a removed entry.",
                "Use removal only when the stable entry is absent from the proposed snapshot.",
            )
        if rationale == "addition" and delta != "added":
            raise _error(
                GraphChangeFailure.INVALID_SEMANTICS,
                f"$.changes[{index}].rationale",
                "The addition rationale does not describe an added entry.",
                "Use addition only for a newly added stable entry.",
            )
        if rationale == "correction" and delta != "changed":
            raise _error(
                GraphChangeFailure.INVALID_SEMANTICS,
                f"$.changes[{index}].rationale",
                "The correction rationale does not describe changed content.",
                "Use correction only when an existing stable entry changed.",
            )
        if rationale in {"challenge", "supersession", "deprecation"}:
            if delta == "removed":
                visible = False
            elif rationale == "challenge":
                visible = _entry_lifecycle(entry) is Lifecycle.CHALLENGED or (
                    isinstance(entry, Relation) and entry.kind is RelationKind.CHALLENGES
                )
            elif rationale == "supersession":
                visible = _entry_lifecycle(entry) is Lifecycle.SUPERSEDED or (
                    isinstance(entry, Relation) and entry.kind is RelationKind.SUPERSEDES
                )
            else:
                visible = _entry_lifecycle(entry) is Lifecycle.DEPRECATED
            if not visible:
                raise _error(
                    GraphChangeFailure.INVALID_SEMANTICS,
                    f"$.changes[{index}].rationale",
                    f"The {rationale} rationale is not visible in the proposed typed entry.",
                    "Publish the matching lifecycle state or typed challenge/supersedes relation.",
                )
    return actual


def validate_graph_change(
    proposal: JsonObject, proposed: Snapshot, base: Snapshot | None = None
) -> JsonObject:
    """Validate exact graph evolution and return its deterministic safe summary."""
    _validate_order_and_proofs(proposal)
    _validate_references(proposal, proposed, base)
    changes = _validate_change_semantics(proposal, proposed, base)
    counts: dict[str, JsonObject] = {
        kind: {
            delta: sum(
                1
                for item_kind, _, item_delta in changes
                if (item_kind, item_delta) == (kind, delta)
            )
            for delta in ("added", "changed", "removed")
        }
        for kind in ("node", "relation")
    }
    return {
        "base_snapshot": None if base is None else snapshot_reference(base),
        "behavior_change": proposal["behavior_change"],
        "change_id": proposal["change_id"],
        "change_kind": proposal["change_kind"],
        "change_schema_version": GRAPH_CHANGE_SCHEMA_VERSION,
        "changed_entry_count": len(changes),
        "node_changes": counts["node"],
        "proposed_snapshot": snapshot_reference(proposed),
        "public_issue": proposal["public_issue"],
        "relation_changes": counts["relation"],
    }
