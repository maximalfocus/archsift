# ArchSift architecture knowledge, verdict-invariant comparison evolution

This is the first governed evolution of ArchSift's finite, open-world reusable
architecture knowledge under FR-015. Its canonical graph schema v1 snapshot is
wheel-packaged at `archsift/knowledge/architecture-v2.json`; its canonical
evolution proposal is packaged beside it as `architecture-v2.change.json`,
names `architecture-v1.json` as its exact immutable base, and is governed by
public issue #101.

Exact publication identity:

- graph schema: `1`
- immutable graph version:
  `gv1:d3970ccc479a767f5f016df19c44c322ed09acbf6a0cbedb4a6be7438dc92217`
- snapshot content identity:
  `sha256:8c08d96ab0ff34bc28dc79c82bdfae03e3f50321d53913586763856d7e94b000`
- inventory: 114 nodes across all 9 node kinds and 89 relations across all 7
  relation kinds

## Scope

The snapshot covers the five control classes ArchSift compares, reusable
concepts and criteria for bounded task, problem/value, credible evidence,
separate architecture decisions, runtime agency, autonomy permission,
candidate comparison, contradiction awareness, ordered elimination, and
verdict resolution. It carries explicit constraints, patterns, independently
authored synthetic counterexamples, and competing/challenged theories. A
challenge or supersession remains a visible typed relation; entries are never
silently merged.

Every rule in packaged ruleset 1.9.0 has one `decision-rule` node with the exact
rule ID and exact source-ID mapping from method 1.3.0. Each rule is reached by
an `informs-rule` relation from its versioned rationale family, so an explicit
private request can construct a complete reusable claim-to-rule trace for any
finding the assessment already emitted. Graph knowledge never emits a finding,
satisfies case evidence, or changes a verdict independently.

## Evidence and limits

The six evidence-source node IDs and their title, publisher, version, and
locator match the packaged public method registry: NIST AI 600-1, NIST AI RMF
1.0, NIST SP 800-30 Rev. 1, NIST SP 800-53 Rev. 5 Update 1, the OECD AI
Recommendation, and W3C PROV-O. Locators are provenance data and are never
opened or fetched. These primary publications inform ArchSift's local claims;
they do not mandate its control classes, evidence thresholds, rules, or
verdicts, and a citation does not prove a claim true.

This snapshot is finite and deliberately not an ontology-completeness claim.
Absence is never evidence that a concept, pattern, theory, source, or
counterexample does not exist. No node, relation, citation, fixture, or source
mapping derives from case material.

## Inspect, extract, and query

The installed package exposes the publication without assuming a package path:

```bash
archsift graph-corpus
archsift graph-corpus --json > architecture-v2.json
archsift graph-snapshot architecture-v2.json
archsift graph-view architecture-v2.json examples/graph-corpus-request.json --json
```

`graph-corpus --json` writes the exact canonical snapshot bytes to standard
output. ArchSift itself remains read-only; shell redirection is the caller's
explicit choice. The example request is independently authored synthetic
material and binds only a rule finding already emitted by the fictional fixed
workflow example.

## Evolution

The evolution proposal validates against its exact immutable base with:

```bash
archsift graph-change architecture-v2.change.json architecture-v2.json --base-snapshot architecture-v1.json
```

This evolution adds the verdict-invariant unknown-comparison rule and its
source-mapped rationale relation. Its proposal names the synthetic inert and
material counterexamples and the regression tests that distinguish them.

Future evolution publishes a new immutable snapshot and a new canonical
proposal naming this snapshot as its exact base. It must account for every
stable-ID content delta, evidence source, visible rationale, and any synthetic
behavior proof under the [graph-change contract](graph-change-v1.md). Neither
this snapshot nor an earlier decision record is rewritten.
