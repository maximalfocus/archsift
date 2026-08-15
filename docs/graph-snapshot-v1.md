# ArchSift architecture knowledge graph snapshot, version 1

This document is the interoperability contract for ArchSift's reusable
architecture knowledge (PRD FR-015). The canonical JSON snapshot and the
semantics described here are the contract; the in-memory representation is an
implementation detail, and no graph database, model API, or cloud service is
required to read or write a snapshot.

A snapshot is **public reusable knowledge**. It never contains a case dossier,
case evidence, a candidate, a task, or a verdict, and the schema has no node or
relation kind that could hold one. A case dossier remains the authority for its
own case.

There is no CLI command for the graph yet. The command and query surface is
defined separately; this version defines only the artifact.

## What a snapshot is

```
{
  "graph_schema_version": 1,
  "graph_version": "gv1:<64 hex>",
  "nodes": [ … ],
  "relations": [ … ],
  "snapshot_content_identity": "sha256:<64 hex>"
}
```

Three values identify a snapshot to any consumer, and a decision record cites
all three rather than embedding snapshot content:

| Value | Answers |
|---|---|
| `graph_schema_version` | Which structure version this snapshot is written in. |
| `graph_version` | *Which knowledge* this is. Derived from the nodes and relations themselves and hashed with them, so identical semantic knowledge always carries the same version. |
| `snapshot_content_identity` | *Which bytes* these are. A lowercase SHA-256 over the complete canonical snapshot excluding only this field. |

Deriving `graph_version` from the knowledge rather than assigning it by hand is
what lets it live inside the hashed payload without making byte-identity
impossible: the same knowledge, imported in any order, reproduces the same
version and the same bytes.

## Nodes

Each node carries a stable semantic identifier (`id`), a `kind`, a `label`, a
`statement`, a `lifecycle` state, its `citations`, and — for evidence sources
only — a `source`.

| `kind` | Holds |
|---|---|
| `concept` | A named idea the method reasons about. |
| `theory` | A theory or claim about when something holds. |
| `architecture-class` | One control class on the spectrum ArchSift compares. |
| `pattern` | A recognisable arrangement within a class. |
| `decision-criterion` | A question a decision must answer. |
| `constraint` | A constraint or veto that bars an option. |
| `decision-rule` | A rule that produces a consequence. |
| `evidence-source` | A source other entries cite. |
| `counterexample` | A case that contradicts a claim. |

Kinds are never conflated: each keeps its role rather than collapsing into one
undifferentiated node type.

### Lifecycle

Every asserted entry declares one epistemic or lifecycle state: `proposed`,
`supported`, `challenged`, `superseded`, or `deprecated`. A superseded or
deprecated entry stays in the snapshot; retirement is recorded by reference,
never by deletion or rewriting.

### Provenance

Every asserted node and every relation carries at least one citation. A
citation names an `evidence-source` node and takes a typed `stance` —
`supports` or `challenges` — so a reader can tell what the source was cited
*for*. When the cited bytes were retained, the citation binds their
`content_identity`; archiving every source is not required, and `null` means
the bytes were not retained rather than that provenance is missing.

An `evidence-source` node records where its content comes from: a `locator`,
the applicable `version` and `publication_state` where they apply, and one
date with its `date_kind` (`observed`, `published`, or `retrieved`) as
appropriate to that source. Evidence sources do not cite other sources; they
are what assertions cite.

**A locator is provenance data, never an instruction.** Nothing in building,
loading, or validating a snapshot dereferences a locator, and no locator is
treated as a path, a command, a template, or a fetch instruction. Handling a
snapshot is offline by construction.

## Relations

A relation carries its own stable semantic identifier, a `kind`, a
`subject_id`, an `object_id`, a `statement`, a `lifecycle` state, and its
citations. Each kind declares which node kinds it may connect; a pair the table
below does not cover has no defined meaning, so the snapshot refuses to assert
it rather than recording something unreadable.

| `kind` | Subject | Object |
|---|---|---|
| `specialises` | pattern, architecture-class, concept | architecture-class, concept |
| `applies-to` | decision-criterion, constraint, decision-rule | architecture-class, pattern, concept |
| `constrains` | constraint | architecture-class, pattern |
| `supports` | theory, counterexample, concept | theory, decision-criterion, decision-rule, constraint |
| `challenges` | theory, counterexample | theory, decision-criterion, decision-rule, constraint, pattern |
| `supersedes` | any asserted kind | any asserted kind |
| `informs-rule` | concept, theory, decision-criterion | decision-rule |

## Competing knowledge stays visible

The domain is open-world. A published snapshot is a finite, enumerable set of
typed nodes and relations, while the domain stays open to evidence-backed
additions, corrections, challenges, supersessions, and removals; **absence from
a snapshot is never evidence that a concept does not exist.**

Conflicting evidence and competing theories coexist as distinct entries. Two
theories that disagree about the same concept are both published, each with its
own lifecycle state and citations, and the disagreement itself can be asserted
as a `challenges` or `supersedes` relation. Loading a snapshot never merges,
deduplicates, or overwrites one assertion with another, so a reviewer sees the
conflict rather than a resolution nobody chose.

## Determinism

Canonical serialization is sorted-key JSON, UTF-8, LF line endings, with a
fixed numeric format and exactly one trailing newline. Nodes and relations are
ordered by semantic identifier. Runtime state, traversal order, layout
coordinates, host paths, generation timestamps, and library-specific objects
never participate: identical semantic knowledge produces byte-identical
snapshots on every supported operating system and Python version.

Semantic identifiers are stable across snapshots. Changing provenance,
lifecycle state, or any other mutable content changes the `graph_version` and
the snapshot content identity while leaving every semantic identifier
unchanged — which is what lets a later snapshot supersede an earlier assertion
by reference.

## Failure is closed

Reading a snapshot fails rather than guessing. Each failure is classified and
maps to the [stable exit-code contract](exit-codes.md):

| Category | Meaning | Exit code |
|---|---|---|
| `invalid-utf8`, `invalid-json` | The file is not readable as unambiguous JSON text. | `10` |
| `unsupported-schema` | The snapshot declares a graph schema version this ArchSift does not support. | `11` |
| `malformed-snapshot`, `unknown-kind`, `undefined-relation`, `dangling-reference`, `duplicate-identifier`, `missing-provenance`, `identity-mismatch` | The snapshot violates the contract above. | `12` |

A snapshot whose declared `graph_version` or `snapshot_content_identity` does
not describe its own content is refused, as are bytes that are not the exact
canonical serialization of the content they carry.

## What a snapshot cannot do

No graph-derived measure — centrality, similarity, embeddings, community
detection, path length, popularity — and no inferred edge exists in this
artifact, and none may ever determine a verdict, promote a more complex class,
satisfy an evidence prerequisite, or stand in for confidence. Reusable
knowledge informs applicability and rationale; a verdict comes from versioned
rules applied to acceptable case evidence.
