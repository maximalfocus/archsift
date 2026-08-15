# ArchSift graph-change proposal, version 1

Graph snapshots are immutable publications. A later snapshot does not edit its
base; it is admitted through a separate, canonical proposal that proves the
exact stable-ID delta and the public evidence and review rationale for every
change. This is the mechanical FR-014/FR-015 evolution boundary.

Validate a proposal and its exact proposed snapshot with:

```bash
archsift graph-change proposal.json proposed-snapshot.json
archsift graph-change proposal.json proposed-snapshot.json --base-snapshot base-snapshot.json
```

The first form is an `initial-publication` and permits no base. The second is an
`evolution` and requires the proposal's base reference to identify the supplied
base bytes exactly. All inputs must be canonical regular files beneath the
current directory. The command is offline, read-only, writes nothing, and never
dereferences a source locator.

## Canonical proposal

Proposal schema version 1 is strict canonical JSON: sorted object keys, compact
separators, ASCII escapes, canonical arrays, and one trailing LF. The packaged
schema rejects unknown fields. A proposal names:

- a stable `change_id` and one public ArchSift issue;
- the exact schema version, immutable graph version, and content identity of
  the proposed snapshot and, for evolution, the base snapshot;
- whether assessment behavior changes, with structural synthetic
  counterexample and regression-test IDs when it does;
- three required true attestations: the material was independently authored
  and synthetic, contains no case material or derivative, and does not treat
  absence from the finite graph as evidence of nonexistence; and
- a unique list sorted by `entry_kind` and stable `id` that declares every and
  only actual node/relation delta.

Each changed entry declares `added`, `changed`, or `removed`; one rationale from
`addition`, `correction`, `challenge`, `supersession`, `deprecation`, or
`removal`; and a sorted unique list of evidence-source IDs. Evidence-source
nodes identify themselves as their provenance anchor. Other proposed asserted
entries must cite exactly the sources the change declares.

## Fail-closed semantics

ArchSift recomputes entry changes by stable semantic ID and canonical entry
content identity. Raw JSON formatting is never treated as evolution. Initial
publication contains additions only. Evolution cannot omit or invent a delta.
Removal is used only for an actually removed entry; addition and correction map
to their corresponding deltas. Challenge, supersession, and deprecation must be
visible in the proposed entry's typed relation or lifecycle state. Every source
ID must resolve in the exact base or proposed snapshot.

A behavior-changing proposal must name at least one independently authored
synthetic counterexample ID and at least one regression test ID. A proposal
that does not change behavior leaves both lists empty. These fields are
structural references, never a place for case narrative.

The validator does not claim that an attestation proves privacy. It makes the
review declaration mandatory and mechanically visible; the public issue form,
pull-request checklist, contribution policy, and regression suite enforce the
same boundary.

## Output and failures

Human output contains only the change ID, exact base/proposed content
identities, and added/changed/removed node/relation counts. It never renders
authored graph text. `--json` returns the same deterministic safe summary;
`--quiet` emits nothing.

Malformed, ambiguous, or invalid-UTF-8 JSON exits `10`; unsupported proposal or
graph schema versions exit `11`; proposal, snapshot-reference, exact-delta,
evidence, attestation, or semantic violations exit `12`; unsafe paths exit
`13`; and missing or unreadable files exit `14`. Diagnostics name the input,
field, FR-014/FR-015 boundary, and remediation.
