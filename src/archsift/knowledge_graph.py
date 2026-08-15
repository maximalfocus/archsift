"""The canonical, content-addressed architecture knowledge graph snapshot.

FR-015: ArchSift maintains a versioned, evidence-backed architecture knowledge
graph as a reusable public layer, separate from any case dossier. This module
owns the artifact and its contract — the typed model, its canonical
serialization, and its addressing — and nothing else. No case view, no rule
wiring, and no effect on assessment or decision records lives here.

Four properties are structural rather than incidental:

* **Typed, not conflated.** Concepts, theories and claims, architecture classes
  and patterns, decision criteria, constraints and vetoes, decision rules,
  evidence sources, and counterexamples are distinct node kinds, and each
  relation kind declares which kinds it may connect. Knowledge keeps its role
  instead of collapsing into one undifferentiated node type.
* **Attributed and revisable.** Every asserted node and relation carries an
  epistemic or lifecycle state and cites its sources with a typed supporting or
  challenging stance. Supersession is a relation to a stable semantic
  identifier, so a later snapshot can retire an assertion without rewriting the
  content-addressed snapshot that first published it.
* **Open-world, not merged.** Competing theories about the same concept are
  distinct entries a reviewer can see. Loading never merges, deduplicates, or
  overwrites one assertion with another, so conflict stays visible instead of
  being resolved silently into a single asserted truth.
* **Deterministic and addressed.** Identical semantic knowledge produces the
  same identifiers, the same immutable graph version, and byte-identical
  snapshot bytes on any platform. Nothing run-variant — traversal order,
  layout, host paths, timestamps, or library objects — can reach the artifact.

Two versions address a snapshot, and they answer different questions. The
**immutable graph version** identifies the *semantic knowledge*: it is derived
from the nodes and relations themselves and lives inside the hashed payload, so
identical knowledge always carries the same version. The **snapshot content
identity** identifies the *serialized snapshot*: a lowercase SHA-256 over the
complete canonical snapshot excluding only the identity field itself.

A source locator is provenance data. Nothing here dereferences one, and no
locator is ever treated as a path, a command, a template, or a fetch
instruction, so building, loading, and validating a snapshot are offline by
construction.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from functools import cache
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from typing import Any, Final, cast

from jsonschema import Draft202012Validator, FormatChecker

from archsift.canonical import JsonObject, canonical_json_bytes
from archsift.diagnostics import ExitCode

GRAPH_SCHEMA_VERSION: Final = 1

#: The field the snapshot content identity is computed without.
_IDENTITY_FIELD: Final = "snapshot_content_identity"
_GRAPH_VERSION_PREFIX: Final = "gv1:"


class NodeKind(StrEnum):
    """The kinds of reusable knowledge a snapshot distinguishes."""

    CONCEPT = "concept"
    THEORY = "theory"
    ARCHITECTURE_CLASS = "architecture-class"
    PATTERN = "pattern"
    DECISION_CRITERION = "decision-criterion"
    CONSTRAINT = "constraint"
    DECISION_RULE = "decision-rule"
    EVIDENCE_SOURCE = "evidence-source"
    COUNTEREXAMPLE = "counterexample"


class RelationKind(StrEnum):
    """The typed relations a snapshot may assert between nodes."""

    SPECIALISES = "specialises"
    APPLIES_TO = "applies-to"
    CONSTRAINS = "constrains"
    SUPPORTS = "supports"
    CHALLENGES = "challenges"
    SUPERSEDES = "supersedes"
    INFORMS_RULE = "informs-rule"


class Lifecycle(StrEnum):
    """The epistemic or lifecycle state of one asserted entry."""

    PROPOSED = "proposed"
    SUPPORTED = "supported"
    CHALLENGED = "challenged"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"


class Stance(StrEnum):
    """How a citation bears on the entry that makes it."""

    SUPPORTS = "supports"
    CHALLENGES = "challenges"


class DateKind(StrEnum):
    """Which date a source records, as appropriate to that source."""

    OBSERVED = "observed"
    PUBLISHED = "published"
    RETRIEVED = "retrieved"


#: An evidence source is the target of citations, not a claim that needs them.
_ASSERTED_NODE_KINDS: Final[frozenset[NodeKind]] = frozenset(
    kind for kind in NodeKind if kind is not NodeKind.EVIDENCE_SOURCE
)

#: Declared semantics: which node kinds each relation may connect. A pair
#: absent here has no defined meaning, so the snapshot refuses to assert it.
_RELATION_DOMAINS: Final[dict[RelationKind, tuple[frozenset[NodeKind], frozenset[NodeKind]]]] = {
    RelationKind.SPECIALISES: (
        frozenset({NodeKind.PATTERN, NodeKind.ARCHITECTURE_CLASS, NodeKind.CONCEPT}),
        frozenset({NodeKind.ARCHITECTURE_CLASS, NodeKind.CONCEPT}),
    ),
    RelationKind.APPLIES_TO: (
        frozenset({NodeKind.DECISION_CRITERION, NodeKind.CONSTRAINT, NodeKind.DECISION_RULE}),
        frozenset({NodeKind.ARCHITECTURE_CLASS, NodeKind.PATTERN, NodeKind.CONCEPT}),
    ),
    RelationKind.CONSTRAINS: (
        frozenset({NodeKind.CONSTRAINT}),
        frozenset({NodeKind.ARCHITECTURE_CLASS, NodeKind.PATTERN}),
    ),
    RelationKind.SUPPORTS: (
        frozenset({NodeKind.THEORY, NodeKind.COUNTEREXAMPLE, NodeKind.CONCEPT}),
        frozenset(
            {
                NodeKind.THEORY,
                NodeKind.DECISION_CRITERION,
                NodeKind.DECISION_RULE,
                NodeKind.CONSTRAINT,
            }
        ),
    ),
    RelationKind.CHALLENGES: (
        frozenset({NodeKind.THEORY, NodeKind.COUNTEREXAMPLE}),
        frozenset(
            {
                NodeKind.THEORY,
                NodeKind.DECISION_CRITERION,
                NodeKind.DECISION_RULE,
                NodeKind.CONSTRAINT,
                NodeKind.PATTERN,
            }
        ),
    ),
    # Supersession retires an earlier assertion of the same kind by reference.
    RelationKind.SUPERSEDES: (
        frozenset(_ASSERTED_NODE_KINDS),
        frozenset(_ASSERTED_NODE_KINDS),
    ),
    RelationKind.INFORMS_RULE: (
        frozenset({NodeKind.CONCEPT, NodeKind.THEORY, NodeKind.DECISION_CRITERION}),
        frozenset({NodeKind.DECISION_RULE}),
    ),
}


class SnapshotFailure(StrEnum):
    """Stable failure categories at the snapshot boundary."""

    INVALID_UTF8 = "invalid-utf8"
    INVALID_JSON = "invalid-json"
    UNSUPPORTED_SCHEMA = "unsupported-schema"
    MALFORMED_SNAPSHOT = "malformed-snapshot"
    UNKNOWN_KIND = "unknown-kind"
    UNDEFINED_RELATION = "undefined-relation"
    DANGLING_REFERENCE = "dangling-reference"
    DUPLICATE_IDENTIFIER = "duplicate-identifier"
    MISSING_PROVENANCE = "missing-provenance"
    IDENTITY_MISMATCH = "identity-mismatch"


class SnapshotFileFailure(StrEnum):
    """Stable failure categories at the snapshot file boundary."""

    ROOT_UNAVAILABLE = "root-unavailable"
    TARGET_MISSING = "target-missing"
    TARGET_UNRESOLVABLE = "target-unresolvable"
    TARGET_OUTSIDE_ROOT = "target-outside-root"
    TARGET_NOT_REGULAR = "target-not-regular"
    TARGET_UNREADABLE = "target-unreadable"


class SnapshotError(ValueError):
    """One safely classified knowledge-graph snapshot failure."""

    def __init__(
        self, category: SnapshotFailure, field: str, message: str, remediation: str
    ) -> None:
        self.category = category
        self.field = field
        self.message = message
        self.remediation = remediation
        super().__init__(message)

    @property
    def exit_code(self) -> ExitCode:
        """Map the stable failure category to the public CLI contract."""
        if self.category is SnapshotFailure.UNSUPPORTED_SCHEMA:
            return ExitCode.UNSUPPORTED_SCHEMA
        if self.category in {SnapshotFailure.INVALID_UTF8, SnapshotFailure.INVALID_JSON}:
            return ExitCode.MALFORMED_INPUT
        return ExitCode.VALIDATION_FAILED

    def to_dict(self) -> dict[str, str]:
        """Return a stable path-free snapshot diagnostic."""
        return {
            "category": self.category.value,
            "field": self.field,
            "message": self.message,
            "remediation": self.remediation,
            "requirement": "FR-015",
        }


def _error(category: SnapshotFailure, field: str, message: str, remediation: str) -> SnapshotError:
    return SnapshotError(category, field, message, remediation)


class SnapshotFileError(ValueError):
    """One safely classified knowledge-graph snapshot file failure."""

    def __init__(
        self,
        category: SnapshotFileFailure,
        field: str,
        message: str,
        remediation: str,
    ) -> None:
        self.category = category
        self.field = field
        self.message = message
        self.remediation = remediation
        super().__init__(message)

    @property
    def exit_code(self) -> ExitCode:
        """Map the stable file category to the public CLI contract."""
        if self.category in {
            SnapshotFileFailure.TARGET_MISSING,
            SnapshotFileFailure.TARGET_UNREADABLE,
        }:
            return ExitCode.ARTEFACT_UNAVAILABLE
        return ExitCode.UNSAFE_PATH


def _file_error(
    category: SnapshotFileFailure,
    field: str,
    message: str,
    remediation: str,
) -> SnapshotFileError:
    return SnapshotFileError(category, field, message, remediation)


@dataclass(frozen=True, slots=True)
class Source:
    """Where an evidence-source node's content comes from.

    ``locator`` is provenance data. It is never dereferenced, opened, executed,
    or treated as a path or template.
    """

    locator: str
    date_kind: DateKind
    dated: date
    version: str | None = None
    publication_state: str | None = None


@dataclass(frozen=True, slots=True)
class Citation:
    """One typed reference from an assertion to an evidence source."""

    source_id: str
    stance: Stance
    #: Present only when the cited bytes were retained; archiving every source
    #: is not required, so absence is normal rather than a gap.
    content_identity: str | None = None


@dataclass(frozen=True, slots=True)
class Node:
    """One reusable knowledge entry with a stable semantic identifier."""

    id: str
    kind: NodeKind
    label: str
    statement: str
    lifecycle: Lifecycle
    citations: tuple[Citation, ...] = ()
    source: Source | None = None


@dataclass(frozen=True, slots=True)
class Relation:
    """One typed, attributed assertion between two nodes."""

    id: str
    kind: RelationKind
    subject_id: str
    object_id: str
    statement: str
    lifecycle: Lifecycle
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One complete, addressed publication of reusable knowledge."""

    graph_schema_version: int
    graph_version: str
    nodes: tuple[Node, ...]
    relations: tuple[Relation, ...]
    snapshot_content_identity: str


def _identity(content: bytes) -> str:
    return f"sha256:{sha256(content).hexdigest()}"


def _citation_dict(citation: Citation) -> JsonObject:
    return {
        "content_identity": citation.content_identity,
        "source_id": citation.source_id,
        "stance": citation.stance.value,
    }


def _source_dict(source: Source) -> JsonObject:
    return {
        "date_kind": source.date_kind.value,
        "dated": source.dated.isoformat(),
        "locator": source.locator,
        "publication_state": source.publication_state,
        "version": source.version,
    }


def _node_dict(node: Node) -> JsonObject:
    return {
        "citations": [_citation_dict(citation) for citation in node.citations],
        "id": node.id,
        "kind": node.kind.value,
        "label": node.label,
        "lifecycle": node.lifecycle.value,
        "source": _source_dict(node.source) if node.source is not None else None,
        "statement": node.statement,
    }


def _relation_dict(relation: Relation) -> JsonObject:
    return {
        "citations": [_citation_dict(citation) for citation in relation.citations],
        "id": relation.id,
        "kind": relation.kind.value,
        "lifecycle": relation.lifecycle.value,
        "object_id": relation.object_id,
        "statement": relation.statement,
        "subject_id": relation.subject_id,
    }


def _semantic_payload(nodes: Sequence[Node], relations: Sequence[Relation]) -> JsonObject:
    """Return the knowledge itself, without either version or the identity.

    Sorting by semantic identifier is what makes re-import order-independent:
    the same knowledge presented in any order yields one payload.
    """
    return {
        "graph_schema_version": GRAPH_SCHEMA_VERSION,
        "nodes": [_node_dict(node) for node in sorted(nodes, key=lambda item: item.id)],
        "relations": [
            _relation_dict(relation) for relation in sorted(relations, key=lambda item: item.id)
        ],
    }


def immutable_graph_version(nodes: Sequence[Node], relations: Sequence[Relation]) -> str:
    """Return the version identifying this semantic knowledge.

    The version is derived from the knowledge rather than assigned, so identical
    semantic inputs always carry the same version — which is what lets it live
    inside the hashed payload without making byte-identity impossible.
    """
    return (
        _GRAPH_VERSION_PREFIX
        + sha256(canonical_json_bytes(_semantic_payload(nodes, relations))).hexdigest()
    )


def _addressed_payload(
    nodes: Sequence[Node], relations: Sequence[Relation], version: str
) -> JsonObject:
    payload = _semantic_payload(nodes, relations)
    payload["graph_version"] = version
    return payload


def canonical_snapshot_dict(snapshot: Snapshot) -> JsonObject:
    """Return the complete snapshot as canonical JSON data."""
    payload = _addressed_payload(snapshot.nodes, snapshot.relations, snapshot.graph_version)
    payload[_IDENTITY_FIELD] = snapshot.snapshot_content_identity
    return payload


def canonical_snapshot_bytes(snapshot: Snapshot) -> bytes:
    """Return strict canonical JSON bytes for one published snapshot."""
    return canonical_json_bytes(canonical_snapshot_dict(snapshot))


def _duplicate(values: Iterable[str]) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


def _check_semantics(nodes: Sequence[Node], relations: Sequence[Relation]) -> None:
    """Reject knowledge the snapshot contract cannot express unambiguously."""
    duplicate = _duplicate(node.id for node in nodes)
    if duplicate is not None:
        raise _error(
            SnapshotFailure.DUPLICATE_IDENTIFIER,
            "$.nodes[].id",
            f"Node identifier {duplicate!r} is declared more than once.",
            "Give every node a distinct stable semantic identifier.",
        )
    duplicate = _duplicate(relation.id for relation in relations)
    if duplicate is not None:
        raise _error(
            SnapshotFailure.DUPLICATE_IDENTIFIER,
            "$.relations[].id",
            f"Relation identifier {duplicate!r} is declared more than once.",
            "Give every relation a distinct stable semantic identifier.",
        )

    by_id = {node.id: node for node in nodes}
    sources = {node.id for node in nodes if node.kind is NodeKind.EVIDENCE_SOURCE}

    for node in nodes:
        if node.kind is NodeKind.EVIDENCE_SOURCE:
            if node.source is None:
                raise _error(
                    SnapshotFailure.MISSING_PROVENANCE,
                    "$.nodes[].source",
                    f"Evidence source {node.id!r} does not record where its content comes from.",
                    "Record the source locator, its version or publication state, and its date.",
                )
            if node.citations:
                raise _error(
                    SnapshotFailure.MALFORMED_SNAPSHOT,
                    "$.nodes[].citations",
                    f"Evidence source {node.id!r} cites another source.",
                    "Cite sources from asserted entries; an evidence source is what they cite.",
                )
            continue
        if node.source is not None:
            raise _error(
                SnapshotFailure.MALFORMED_SNAPSHOT,
                "$.nodes[].source",
                f"Asserted node {node.id!r} records a source of its own.",
                "Give only evidence-source nodes a source; assertions cite them instead.",
            )
        if not node.citations:
            raise _error(
                SnapshotFailure.MISSING_PROVENANCE,
                "$.nodes[].citations",
                f"Asserted node {node.id!r} carries no provenance.",
                "Cite at least one evidence source that supports or challenges it.",
            )
        _check_citations(node.id, node.citations, sources, "$.nodes[].citations")

    for relation in relations:
        domains = _RELATION_DOMAINS[relation.kind]
        for role, identifier in (("subject", relation.subject_id), ("object", relation.object_id)):
            target = by_id.get(identifier)
            if target is None:
                raise _error(
                    SnapshotFailure.DANGLING_REFERENCE,
                    f"$.relations[].{role}_id",
                    f"Relation {relation.id!r} names unknown node {identifier!r}.",
                    "Reference only semantic identifiers declared in this snapshot.",
                )
            allowed = domains[0] if role == "subject" else domains[1]
            if target.kind not in allowed:
                raise _error(
                    SnapshotFailure.UNDEFINED_RELATION,
                    f"$.relations[].{role}_id",
                    (
                        f"Relation kind {relation.kind.value!r} has no defined meaning with a "
                        f"{target.kind.value!r} {role}."
                    ),
                    "Use a relation kind whose declared semantics cover both node kinds.",
                )
        if relation.subject_id == relation.object_id:
            raise _error(
                SnapshotFailure.UNDEFINED_RELATION,
                "$.relations[].object_id",
                f"Relation {relation.id!r} relates node {relation.subject_id!r} to itself.",
                "Relate two distinct semantic identifiers.",
            )
        if not relation.citations:
            raise _error(
                SnapshotFailure.MISSING_PROVENANCE,
                "$.relations[].citations",
                f"Relation {relation.id!r} carries no provenance.",
                "Cite at least one evidence source that supports or challenges it.",
            )
        _check_citations(relation.id, relation.citations, sources, "$.relations[].citations")


def _check_citations(
    owner: str,
    citations: Sequence[Citation],
    sources: frozenset[str] | set[str],
    field: str,
) -> None:
    for citation in citations:
        if citation.source_id not in sources:
            raise _error(
                SnapshotFailure.DANGLING_REFERENCE,
                f"{field}.source_id",
                f"{owner!r} cites unknown evidence source {citation.source_id!r}.",
                "Cite only evidence-source nodes declared in this snapshot.",
            )
        identity = citation.content_identity
        if identity is None:
            continue
        if (
            type(identity) is not str
            or len(identity) != 71
            or not identity.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in identity[7:])
        ):
            raise _error(
                SnapshotFailure.MALFORMED_SNAPSHOT,
                f"{field}.content_identity",
                f"{owner!r} binds a malformed cited-content identity.",
                "Bind a lowercase sha256:<64 hex> identity, or omit it when bytes"
                " are not retained.",
            )


def build_snapshot(nodes: Sequence[Node], relations: Sequence[Relation]) -> Snapshot:
    """Return one addressed snapshot of the given semantic knowledge.

    Building is deterministic and order-independent: the same knowledge, in any
    order, yields the same identifiers, the same immutable graph version, and
    byte-identical snapshot bytes.
    """
    _check_semantics(nodes, relations)
    version = immutable_graph_version(nodes, relations)
    payload = _addressed_payload(nodes, relations, version)
    identity = _identity(canonical_json_bytes(payload))
    ordered_nodes = tuple(sorted(nodes, key=lambda item: item.id))
    ordered_relations = tuple(sorted(relations, key=lambda item: item.id))
    return Snapshot(
        graph_schema_version=GRAPH_SCHEMA_VERSION,
        graph_version=version,
        nodes=ordered_nodes,
        relations=ordered_relations,
        snapshot_content_identity=identity,
    )


@cache
def _snapshot_validator() -> Draft202012Validator:
    raw = json.loads(
        files("archsift")
        .joinpath("schemas/graph-snapshot-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if type(raw) is not dict:
        raise TypeError("packaged graph-snapshot schema must be an object")
    return Draft202012Validator(cast(dict[str, Any], raw), format_checker=FormatChecker())


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _error(
                SnapshotFailure.INVALID_JSON,
                "$",
                f"The snapshot repeats the JSON field {key!r}.",
                "Emit each field once; a repeated field has no unambiguous value.",
            )
        result[key] = value
    return result


def _citation(raw: Mapping[str, Any]) -> Citation:
    identity = raw.get("content_identity")
    return Citation(
        source_id=str(raw["source_id"]),
        stance=Stance(str(raw["stance"])),
        content_identity=None if identity is None else str(identity),
    )


def _source(raw: Mapping[str, Any]) -> Source:
    version = raw.get("version")
    state = raw.get("publication_state")
    return Source(
        locator=str(raw["locator"]),
        date_kind=DateKind(str(raw["date_kind"])),
        dated=date.fromisoformat(str(raw["dated"])),
        version=None if version is None else str(version),
        publication_state=None if state is None else str(state),
    )


def _typed_kind(value: str, kinds: type[NodeKind] | type[RelationKind], field: str) -> Any:
    try:
        return kinds(value)
    except ValueError as error:
        raise _error(
            SnapshotFailure.UNKNOWN_KIND,
            field,
            f"{value!r} is not a kind this graph schema version defines.",
            "Use a declared kind, or publish under a graph schema version that defines it.",
        ) from error


def load_snapshot(content: bytes) -> Snapshot:
    """Load, validate, and re-verify one published snapshot's own addressing.

    Loading never merges, deduplicates, or reconciles entries: competing
    assertions about the same concept arrive exactly as they were published,
    so a reviewer sees the conflict rather than a resolution nobody chose.
    """
    try:
        text = content.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise _error(
            SnapshotFailure.INVALID_UTF8,
            "$",
            "The snapshot file is not valid UTF-8.",
            "Replace it with the exact canonical bytes the snapshot was published as.",
        ) from error
    try:
        loaded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"unsupported JSON constant {value}")
            ),
        )
    except SnapshotError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise _error(
            SnapshotFailure.INVALID_JSON,
            "$",
            "The snapshot file is not unambiguous JSON.",
            "Replace it with the exact canonical bytes the snapshot was published as.",
        ) from error
    if type(loaded) is not dict:
        raise _error(
            SnapshotFailure.MALFORMED_SNAPSHOT,
            "$",
            "The snapshot root is not a JSON object.",
            "Publish a snapshot object with nodes, relations, and its versions.",
        )
    raw = cast(dict[str, Any], loaded)

    declared = raw.get("graph_schema_version")
    if type(declared) is int and declared != GRAPH_SCHEMA_VERSION:
        raise _error(
            SnapshotFailure.UNSUPPORTED_SCHEMA,
            "$.graph_schema_version",
            f"Graph schema version {declared!r} is not supported.",
            f"Use graph schema version {GRAPH_SCHEMA_VERSION} or upgrade ArchSift.",
        )
    schema_error = next(_snapshot_validator().iter_errors(raw), None)
    if schema_error is not None:
        field = "$" + "".join(
            f".{part}" if type(part) is str else "[]" for part in schema_error.path
        )
        raise _error(
            SnapshotFailure.MALFORMED_SNAPSHOT,
            field,
            f"The snapshot does not satisfy graph schema version {GRAPH_SCHEMA_VERSION}.",
            f"Correct {field}: {schema_error.message}",
        )

    nodes = tuple(
        Node(
            id=str(item["id"]),
            kind=_typed_kind(str(item["kind"]), NodeKind, "$.nodes[].kind"),
            label=str(item["label"]),
            statement=str(item["statement"]),
            lifecycle=Lifecycle(str(item["lifecycle"])),
            citations=tuple(_citation(citation) for citation in item.get("citations", ())),
            source=None if item.get("source") is None else _source(item["source"]),
        )
        for item in cast(Sequence[Mapping[str, Any]], raw["nodes"])
    )
    relations = tuple(
        Relation(
            id=str(item["id"]),
            kind=_typed_kind(str(item["kind"]), RelationKind, "$.relations[].kind"),
            subject_id=str(item["subject_id"]),
            object_id=str(item["object_id"]),
            statement=str(item["statement"]),
            lifecycle=Lifecycle(str(item["lifecycle"])),
            citations=tuple(_citation(citation) for citation in item.get("citations", ())),
        )
        for item in cast(Sequence[Mapping[str, Any]], raw["relations"])
    )
    _check_semantics(nodes, relations)

    snapshot = build_snapshot(nodes, relations)
    if raw["graph_version"] != snapshot.graph_version:
        raise _error(
            SnapshotFailure.IDENTITY_MISMATCH,
            "$.graph_version",
            "The declared immutable graph version does not describe this knowledge.",
            "Republish the snapshot so its version is derived from its own nodes and relations.",
        )
    if raw[_IDENTITY_FIELD] != snapshot.snapshot_content_identity:
        raise _error(
            SnapshotFailure.IDENTITY_MISMATCH,
            f"$.{_IDENTITY_FIELD}",
            "The declared snapshot content identity does not address these bytes.",
            "Republish the snapshot so its identity is computed from its own canonical bytes.",
        )
    if canonical_snapshot_bytes(snapshot) != content:
        raise _error(
            SnapshotFailure.MALFORMED_SNAPSHOT,
            "$",
            "The snapshot bytes are not the canonical serialization of their own content.",
            "Publish the exact canonical bytes ArchSift emits for this snapshot.",
        )
    return snapshot


def _resolve_snapshot_path(path: Path, *, root: Path) -> Path:
    try:
        authorised_root = root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _file_error(
            SnapshotFileFailure.ROOT_UNAVAILABLE,
            "$",
            "The snapshot root cannot be resolved to an authorised directory.",
            "Run graph-snapshot from an existing resolvable directory containing the snapshot.",
        ) from error
    if not authorised_root.is_dir():
        raise _file_error(
            SnapshotFileFailure.ROOT_UNAVAILABLE,
            "$",
            "The snapshot root is not an authorised directory.",
            "Run graph-snapshot from the directory containing the published snapshot.",
        )
    candidate = path if path.is_absolute() else authorised_root / path
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError) as error:
        raise _file_error(
            SnapshotFileFailure.TARGET_MISSING,
            "$",
            "The knowledge-graph snapshot file does not exist.",
            "Provide an existing canonical JSON snapshot file beneath the current directory.",
        ) from error
    except (OSError, RuntimeError) as error:
        raise _file_error(
            SnapshotFileFailure.TARGET_UNRESOLVABLE,
            "$",
            "The knowledge-graph snapshot path cannot be resolved safely.",
            "Remove unsafe or looping links and provide a resolvable snapshot path.",
        ) from error
    if not resolved.is_relative_to(authorised_root):
        raise _file_error(
            SnapshotFileFailure.TARGET_OUTSIDE_ROOT,
            "$",
            "The knowledge-graph snapshot path resolves outside the authorised root.",
            "Place the snapshot beneath the current directory and use that contained path.",
        )
    try:
        mode = resolved.stat().st_mode
    except OSError as error:
        raise _file_error(
            SnapshotFileFailure.TARGET_UNRESOLVABLE,
            "$",
            "The knowledge-graph snapshot file cannot be inspected safely.",
            "Provide a resolvable regular file beneath the current directory.",
        ) from error
    if not stat.S_ISREG(mode):
        raise _file_error(
            SnapshotFileFailure.TARGET_NOT_REGULAR,
            "$",
            "The knowledge-graph snapshot path is not a regular file.",
            "Provide a regular canonical JSON snapshot file.",
        )
    return resolved


def _read_snapshot_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as error:
        raise _file_error(
            SnapshotFileFailure.TARGET_MISSING,
            "$",
            "The knowledge-graph snapshot disappeared before it could be read.",
            "Provide an existing stable canonical JSON snapshot file.",
        ) from error
    except PermissionError as error:
        raise _file_error(
            SnapshotFileFailure.TARGET_UNREADABLE,
            "$",
            "The knowledge-graph snapshot file cannot be read.",
            "Grant read access or provide another readable canonical snapshot.",
        ) from error
    except OSError as error:
        raise _file_error(
            SnapshotFileFailure.TARGET_UNRESOLVABLE,
            "$",
            "The knowledge-graph snapshot file cannot be opened safely.",
            "Remove unsafe links and provide a stable regular file.",
        ) from error
    try:
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            try:
                surface = path.lstat()
            except OSError as error:
                raise _file_error(
                    SnapshotFileFailure.TARGET_UNRESOLVABLE,
                    "$",
                    "The knowledge-graph snapshot path changed while it was being opened.",
                    "Provide a stable regular canonical JSON snapshot file.",
                ) from error
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(surface.st_mode)
                or not os.path.samestat(opened, surface)
            ):
                raise _file_error(
                    SnapshotFileFailure.TARGET_NOT_REGULAR,
                    "$",
                    "The opened knowledge-graph snapshot input is not a regular file.",
                    "Provide a regular canonical JSON snapshot file.",
                )
            return stream.read()
    except SnapshotFileError:
        raise
    except OSError as error:
        raise _file_error(
            SnapshotFileFailure.TARGET_UNREADABLE,
            "$",
            "The knowledge-graph snapshot file cannot be read.",
            "Grant read access or provide another readable canonical snapshot.",
        ) from error


def load_snapshot_file(path: Path, *, root: Path) -> Snapshot:
    """Safely read and validate one published snapshot beneath an authorised root."""
    resolved = _resolve_snapshot_path(path, root=root)
    return load_snapshot(_read_snapshot_bytes(resolved))


def snapshot_reference(snapshot: Snapshot) -> JsonObject:
    """Return the three values that identify a snapshot to any consumer.

    A decision record cites a snapshot by these values (FR-011) rather than by
    embedding its content, so a later reader can tell exactly which published
    knowledge a finding used.
    """
    return {
        "graph_schema_version": snapshot.graph_schema_version,
        "graph_snapshot_content_identity": snapshot.snapshot_content_identity,
        "graph_version": snapshot.graph_version,
    }
