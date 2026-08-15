# ArchSift

**The minimum-sufficient architecture—or the evidence you still need.**

ArchSift is an open-source, local-first decision-support project for comparing human-owned work, process redesign, deterministic automation, fixed AI workflows, and runtime model-directed agency. It is designed to make evidence and trade-offs inspectable, and it may abstain when the available evidence cannot support a defensible decision.

> [!IMPORTANT]
> ArchSift is currently pre-alpha. The CLI can validate typed evidence, task, problem-value, agency-necessity, autonomy-permission, and candidate-comparison facts, inspect the packaged ruleset, produce immutable content-addressed JSON decision records with deterministic injection-safe Markdown review views, and compare reassessments without mutating either record. The deterministic assessment core resolves minimum-sufficient architecture verdicts and binds canonical dossiers, explicit evidence-artefact bytes, ruleset, configuration, and tool version into each final record identity. User-selected output paths are not implemented yet.

## Publication and validation status

Only this implementation repository is intended for public source publication. Private requirements,
private case dossiers, case evidence, findings, and operational rationale remain outside it. Repository
visibility does not publish a package, tag, GitHub release, deployment, hosted service, or
documentation site by itself; those events occur only through an explicit release action. The first
public release — the version tag and GitHub release — was published on 2026-08-15; the PyPI package has
not been published yet, and no deployment, hosted service, or documentation site has been published.

The independent CLI usability cohort (simulated protocol 2.0.0) has been completed and its
committed result validates with `criterion-met` (four of four simulated sessions passed; see
[`usability-results.json`](usability-results.json)). The independent architecture-method review
(simulated protocol 2.0.0) has also been completed; see the protocol and results below. No
method-validation, certification, production-readiness, or first-release success claim is made; the
usability and method-review evidence is simulated: no claim that human target users passed is made,
and no claim that human architects passed is made.

## Install

ArchSift requires a supported CPython version starting with Python 3.11. Once the
package is published on PyPI, install it with:

```bash
python -m pip install archsift
archsift --version
```

The PyPI package has not been published yet; until then, install from a source
checkout:

```bash
git clone https://github.com/maximalfocus/archsift.git
cd archsift
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

See [the usage reference](docs/usage.md) for the complete command surface,
workspace and dossier structure, decision-record outputs, and masking policy.

## Current CLI

```bash
archsift --version
python -m archsift --version
archsift init my-case
archsift validate my-case
archsift validate my-case --json
archsift rules
archsift rules --json
archsift assess my-case
archsift assess my-case --json
archsift assess my-case --external-evidence-root ../authorised-evidence --json
archsift assess my-case --graph-snapshot snapshot.json --graph-request request.json --json
archsift report my-case/output/sha256-<record-id>.json
archsift report my-case/output/sha256-<record-id>.json --format html --level detailed
archsift report my-case/output/sha256-<record-id>.json --format html --level executive
archsift report my-case/output/sha256-<record-id>.json --format pptx --level executive
archsift compare output/sha256-<old-id>.json output/sha256-<new-id>.json
archsift compare output/sha256-<old-id>.json output/sha256-<new-id>.json --json
archsift graph-corpus
archsift graph-corpus --json
archsift graph-snapshot tests/golden/graph-snapshot-v1.json
archsift graph-snapshot tests/golden/graph-snapshot-v1.json --json
archsift graph-change proposal.json proposed-snapshot.json --json
archsift graph-change proposal.json proposed-snapshot.json --base-snapshot base-snapshot.json --json
archsift graph-view snapshot.json private-case-view-request.json --json
archsift usability-results usability-results.json
archsift method-review-results method-review-results.json
```

`init` creates `case.yaml` declaring `language: en`, workspace guidance rendered in that language, and empty `evidence/` and `output/` directories. The dossier captures optional operational task, problem-value, agency-necessity, autonomy-permission, and candidate-comparison boundaries and distinguishes observations, assumptions, estimates, and known gaps without opening dossier-supplied paths. Schema version 2 adds an explicit evidence authorship and accountable-person attestation boundary while preserving schema-version-1 validation and canonical identities; unattested assistant-authored observations and estimates cannot satisfy a credible-evidence rule. `validate` safely checks the versioned dossier, reports deterministic prerequisite readiness in JSON mode, and fails closed on malformed, unsupported, unknown, duplicate, or unsafe input. Each case declares a `language` code defaulting to `en` — the language ArchSift generates workspace guidance and every report in, and part of the dossier bytes the record is addressed by, so changing it produces a distinct record; English is the only supported language today, an unknown or unsupported code fails closed, and the language of authored prose is a convention ArchSift never inspects or validates as truth. `rules` lists the immutable packaged rules and their stable public rationale/source mappings without requiring a case workspace. The [versioned method specification](docs/method-v1.4.0.md) defines the current decision constitution, evidence truth boundary, rule rationale, citations, explicit limits, and rule-change governance.

`assess` validates first, hashes only explicit workspace artefacts or external artefacts beneath the caller-granted `--external-evidence-root`, and writes canonical JSON plus a Markdown review view to `output/sha256-<record-id>.json` and `.md`. Both files share the record identity; identical reruns reuse byte-identical outputs without rewriting them, and a non-identical file at either path is never overwritten. Every authored Markdown value is visibly quoted as inert data, including provenance and artefact paths, and no locator is dereferenced. `--json` still emits only the exact canonical JSON bytes, while human and quiet modes never render dossier-authored text. Before either representation is emitted, authored strings are passed through a deterministic offline sensitive-value masking policy; both outputs disclose the masking and warn that a record is not guaranteed to be sensitive-data-free and still requires handling appropriate to its source material. See the [stable exit-code contract](docs/exit-codes.md) and the [usage reference](docs/usage.md).

Optional paired `--graph-snapshot` and `--graph-request` inputs bind a deterministic private case view only after ordinary assessment. Each private finding ID must exactly match a rule ID already emitted by that assessment, and at least one complete reusable claim-to-rule trace must exist. The resulting `graph_use` record section addresses the exact snapshot, private view, and finding-relevant reusable nodes and relations; graph gaps, conflicts, topology, or absence never change the assessment or verdict. Omitting both options preserves the legacy no-graph record bytes and identity.

`report` renders a generated record beside it as a detailed HTML report (`output/sha256-<record-id>.detailed.html`) or an executive summary in HTML and PPTX (`.executive.html`, `.executive.pptx`). The detailed report states the same content as the Markdown review view. The executive summary states the case and task boundary in brief, the verdict or abstention with its rule ID, the decision space, active vetoes and mandatory human controls, the evidence state with its material gaps, and the directional trade-offs the verdict rests on; both of its formats render one summary, so they cannot state different facts, and neither introduces anything the record does not contain. Every report is an output of the record rather than a separate authoritative artifact: its name restates the record's content identity and it derives no identity of its own. Reports are self-contained and offline — no network resource, script, font, image, external stylesheet, or embedded media; ArchSift writes the PPTX package itself rather than depending on a presentation library. Every authored string is rendered as inert text rather than markup, attribute, URL, or presentation XML, the record's masking policy is applied to every report, and identical inputs produce byte-identical output with the same reuse and never-overwrite discipline as the record itself.

Reassessment means running `assess` again after the dossier, evidence artefacts, ruleset, configuration, tool version, or bound graph input changes; the result is a new immutable content-addressed record. `compare` reads two generated records beneath the current directory and reports evidence-identity, attestation, finding/ruleset, verdict-field, and graph-use changes. Attestation changes are named explicitly and classified as causes when they change evidence eligibility or verdict fields. Graph presence and exact identifiers are explicit; only addressed reusable nodes and relations that reached findings are diffed, while identity-only snapshot evolution remains context. Finding-relevant graph changes are cause candidates only alongside changed verdict fields and can never independently determine a verdict. The command is offline and read-only, and `--json` emits comparison schema version 3 as canonical JSON.

The [architecture knowledge graph snapshot contract](docs/graph-snapshot-v1.md) defines the reusable public knowledge layer: typed nodes and relations with declared semantics, provenance and an epistemic state on every assertion, competing theories kept visibly in conflict rather than merged, and canonical bytes addressed by an immutable graph version and a snapshot content identity. A snapshot never contains case material, a source locator is provenance that is never dereferenced, and no graph-derived measure or inferred edge may determine a verdict. `graph-snapshot` safely validates one canonical published snapshot beneath the current directory, re-verifies both addressing values, and reports its typed node and relation inventory without writing, fetching, or querying anything.

The [graph-change proposal contract](docs/graph-change-v1.md) makes publication and evolution reviewable. `graph-change` checks one public issue, mandatory privacy and open-world attestations, exact immutable base/proposed identities, every stable-ID semantic delta, evidence-source bindings, visible lifecycle or typed-relation rationales, and synthetic proof for behavior changes. It is deterministic, offline, read-only, and never renders authored graph text.

The [current architecture knowledge publication](docs/architecture-knowledge-v2.md) is a wheel-packaged immutable snapshot with all graph node/relation kinds, all five control classes, all six public method sources, and one exact source-mapped decision-rule node and complete rationale path for every packaged rule. `graph-corpus` reports its identity or emits its exact canonical bytes without assuming an installation path. The corpus is finite and open-world: absence is never evidence of nonexistence, and its public sources inform rather than mandate ArchSift's local design. The immutable [initial publication](docs/architecture-knowledge-v1.md) remains packaged as the exact evolution base.

`graph-view` combines a validated published snapshot with one explicit, canonical private request naming relevance roots and private finding-to-rule bindings. It returns a deterministic private view with reusable claim traces, visible conflicts, and reusable-knowledge gaps; it never infers applicability, changes a verdict, persists the view, or merges case material into the public snapshot.

No network service, model API, or telemetry is used by the current CLI.

The [independent CLI usability-check protocol](docs/usability-check-v1.md) freezes a fictional,
domain-neutral five-session human check and its privacy-bounded result contract. The
[simulated usability-check protocol](docs/usability-check-v2.md) freezes the initial-release
gate: four independent simulated sessions by distinct agent products, criterion met when at least
three pass. The initial simulated cohort has run and its committed
[result](usability-results.json) validates with `criterion-met`; the human protocol has not been
run and no human-participant claim is made. A completed cohort is checked offline with exactly
`archsift usability-results usability-results.json`.

The [independent architecture-method review protocol](docs/method-review-v1.md) freezes a
four-example causal-trace review and privacy-bounded result contract for the public method. The
[simulated architecture-method review protocol](docs/method-review-v2.md) freezes the
initial-release gate: four independent simulated review sessions by distinct agent products,
criterion met when at least three pass. The second simulated cohort has run and its committed
[result](method-review-results.json) remains valid historical evidence with
`criterion-met-superseded` (three of four sessions passed) for method `1.2.0`, ruleset `1.8.0`,
and corpus `1.0.0`; the first cohort is preserved as an honest historical
[record](method-review-results-1-criterion-not-met.json) with
`criterion-not-met-superseded` for that same binding;
the human protocol has not been run. Results for a packaged superseded binding remain loadable as
historical evidence, name the binding, and exit `16` so they cannot be read as current success;
unregistered bindings fail closed.
The evidence is simulated, and no claim that a human architect passed is made. A completed result
is checked offline with exactly `archsift method-review-results method-review-results.json`, which
now exits `16` because the reviewed method/ruleset binding is superseded.

## Runnable examples

Four self-contained, fictional workspaces cover no technology change, fixed AI workflow, agentic
control, and insufficient evidence. Run one directly from the repository root:

```bash
python -m archsift validate examples/fixed-workflow --json
python -m archsift assess examples/fixed-workflow --json
```

See [the runnable examples](examples/) for expected outcomes, trace pointers, and all four cases.

## Development gate

```bash
python -m pytest
python -m benchmarks.large_dossier --max-seconds 2.0
python -m ruff check .
python -m ruff format --check .
python -m mypy src benchmarks tests/test_performance.py
python -m build
```

## Contributing and security

Development is issue-driven. Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a change. Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Licence

Apache License 2.0. See [LICENSE](LICENSE).
