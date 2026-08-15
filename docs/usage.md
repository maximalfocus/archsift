# ArchSift usage

ArchSift is a local-first command-line tool that compares human-owned work, process
redesign, deterministic automation, fixed AI workflows, and runtime model-directed
agency for a bounded business task, and either recommends the minimum-sufficient
architecture or states exactly what evidence is still missing. It runs entirely
offline: no network service, model API, or telemetry is used.

This guide covers installation, the complete command surface, the case workspace
and dossier, decision-record outputs (including report rendering and
sensitive-value masking), comparison and reassessment, and published knowledge-graph
corpus inspection, snapshot validation, and governed evolution. The
[versioned method specification](method-v1.2.0.md)
defines the decision constitution and rule rationale; the
[stable exit-code contract](exit-codes.md) defines every command's exit codes.

## Installation

ArchSift requires a supported CPython version starting with Python 3.11.

Once the package is published, install it from PyPI:

```bash
python -m pip install archsift
archsift --version
```

Until the package is published, install from a source checkout:

```bash
git clone https://github.com/maximalfocus/archsift.git
cd archsift
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
archsift --version
```

The published package is a pure-Python wheel with no compiler requirement. No
publication event has occurred yet; repository visibility does not publish a
package, tag, GitHub release, or documentation site.

## Quick start

The four runnable synthetic examples are the fastest way to exercise the tool.
From the repository root:

```bash
python -m archsift validate examples/no-technology-change --json
python -m archsift assess examples/no-technology-change --json
```

See [the runnable examples](../examples/) for all four workspaces, their expected
verdicts, and the machine-readable manifest that pins them.

## Command reference

Every command accepts exactly one of the output options:

| Option | Effect |
|---|---|
| *(none)* | Concise human-readable output on stdout; diagnostics on stderr. |
| `--json` | Stable canonical JSON payload on stdout. |
| `--quiet` | No output at all; only the exit code is available. |

`--json` and `--quiet` are mutually exclusive. Invalid input never produces a
successful-looking report. Every command also accepts the standard `-h` /
`--help` options.

### `archsift` `--version`

Prints the installed ArchSift version and exits.

### `archsift init <case>`

Creates a versioned case workspace at the given directory. The target must not
exist or must be empty. `init` writes `case.yaml` (schema version 1) declaring
`language: en`, a workspace README with human-readable guidance rendered in that
language, and empty `evidence/` and `output/` directories. It never overwrites
existing files, and identical inputs produce byte-identical output.

### `archsift validate <case>`

Validates the dossier at `<case>/case.yaml`: schema version, references,
evidence-ledger integrity, task-boundary contract, problem-value,
agency-necessity, autonomy-permission, and candidate-comparison prerequisites,
and cross-section consistency. It fails closed on malformed, unsupported,
unknown, duplicate, or unsafe input, and never opens dossier-supplied paths.

`--json` reports `status: "valid"` or `"invalid"` plus structured readiness
details (evidence count, defined sections, prerequisite readiness, veto and
control counts, and consistency readiness) and every diagnostic with its file,
field, governing requirement, and remediation.

A valid but incomplete dossier validates successfully; the assessment may then
abstain with `insufficient-evidence`.

### `archsift assess <case>` [`--external-evidence-root` <dir>] [`--graph-snapshot` <snapshot> `--graph-request` <request>]

Validates the workspace first, then composes an immutable content-addressed
decision record and writes two outputs to `<case>/output/`:

- `sha256-<record-id>.json` — the canonical machine-readable record;
- `sha256-<record-id>.md` — the Markdown review view for architecture review.

Both files share the record identity. `--external-evidence-root` `<dir>`
explicitly authorises one external directory holding evidence artefacts
referenced by the dossier; without the grant, assessment fails rather than
reading an external root. Artefact bytes beneath the workspace or the granted
root are hashed into the record; paths are never dereferenced as instructions.

Identical reruns reuse byte-identical outputs without rewriting them, and a
non-identical file at either identity-derived path is never overwritten.
Reassessing after any input change (dossier, evidence bytes, ruleset,
configuration, or tool version) produces a new distinct record.

`--graph-snapshot` and `--graph-request` are optional but must be supplied
together. Both canonical JSON files must be regular files beneath the current
directory. ArchSift constructs the same private view as `graph-view` only after
ordinary assessment and requires every request `finding_id` to exactly match a
`rule_id` already emitted by that assessment. At least one reusable claim must
have a complete declared relation path through a reusable decision rule to one
of those findings.

When that boundary is satisfied, the canonical record and Markdown review view
gain a `graph_use` section containing the graph schema version, immutable graph
version, snapshot content identity, private-view content identity, supported
finding rule IDs, and content-addressed reusable node and relation references
that reached those findings. The detailed HTML report renders the same section.
These values participate in the record identity. Graph conflicts and reusable-
knowledge gaps remain review context: they cannot become case-evidence gaps,
satisfy a prerequisite, change confidence, eliminate a class, or alter the
verdict. Omitting both graph options emits the exact legacy no-graph bytes and
identity.

`--json` emits exactly the canonical JSON record bytes. Human and quiet modes
never render dossier-authored text.

### `archsift report <record>` [`--format` html|pptx] [`--level` detailed|executive]

Renders a generated canonical decision-record JSON file beneath the current
directory as a standalone report. Three combinations are supported:

| `--format` | `--level` | Output | Audience |
|---|---|---|---|
| `html` | `detailed` *(default)* | `sha256-<record-id>.detailed.html` | architecture review |
| `html` | `executive` | `sha256-<record-id>.executive.html` | stakeholder summary |
| `pptx` | `executive` | `sha256-<record-id>.executive.pptx` | stakeholder presentation |

`--format pptx --level detailed` has no renderer and is rejected as a usage
error rather than silently producing something else.

The **detailed** report states the same content as the Markdown review view:
task boundary, candidate comparison, the four decision areas, vetoes,
recommendation or abstention, trade-offs, evidence links with their content
identities, unresolved gaps, the dossier schema, ruleset and tool versions, and
reassessment triggers.

The **executive** summary states the case identity and task boundary in brief,
the verdict or abstention with its rule ID, the decision space and each
candidate's role, the active vetoes and mandatory human controls, the evidence
state with its counts and material gaps, and the trade-offs that most affect
the verdict — the directional comparison outcomes involving a candidate the
verdict rests on. The HTML and PPTX forms render one summary, so they cannot
state different facts about the same record. The summary introduces nothing the
record does not contain: every value is verbatim record content apart from
counts and fixed markers for an absent, empty, or abstaining outcome. Nothing
is truncated; a section longer than one slide continues onto the next.

Every report is written beside the record it renders and is an output of that
record rather than a separate authoritative artifact: its name restates the
record's content identity and it derives no identity of its own. Identical
reruns reuse the byte-identical file without rewriting it, and a non-identical
file at the derived path is preserved rather than overwritten.

Every report is fully self-contained and offline. The HTML references no
network resource, script, font, image, or external stylesheet. The PPTX deck is
written by ArchSift itself, embeds no media, and requires no external font,
image, or template. Every authored string is rendered as inert text — never as
markup, script, attribute, URL, or presentation XML — and the same
sensitive-value masking policy applied to the record is applied to every
report. Rendering is deterministic: identical inputs produce byte-identical
output, and the deck carries no generation timestamp.

`--json` reports the record identity, the rendered format and level, the output
path, and whether an existing byte-identical report was reused.

### `archsift compare <old> <new>`

Reads two generated canonical decision-record JSON files beneath the current
directory and explains the differences: changed evidence identities, changed
findings and rules, changed verdict fields, and unrelated snapshot context.
A verdict change names only changed evidence cited by a finding in either record
and the changed findings as causes.

Comparison schema version 2 always includes `changed_graph`. It states graph-use
presence in both records; exact old/new graph schema, immutable graph version,
snapshot content identity, and private-view content identity; added or removed
supported finding rule IDs; and added, removed, or content-changed reusable
nodes and relations keyed by stable semantic ID. Those entry deltas come only
from the finding-relevant references frozen into either record. ArchSift never
reloads a historical snapshot or dereferences its source locators.

A graph identity change with no finding-relevant entry change is snapshot
context, never a reusable-assertion change or verdict cause. Finding-relevant
entry and supported-finding changes are named as cause candidates only when
verdict fields also changed; otherwise they remain reassessment context. This
classification never lets graph knowledge independently alter a verdict,
satisfy case evidence, or infer causality. The command is offline and read-only;
`--json` emits the stable canonical comparison payload and quiet mode emits
nothing.

### `archsift rules` [--json]

Lists the immutable packaged decision rules: rule IDs, versions, descriptions,
effects, and their public rationale and source mappings. No case workspace is
required. `--json` emits the stable ruleset catalog including the versioned
method specification reference.

### `archsift graph-corpus`

Reports the exact identity and typed inventory of the wheel-packaged
[initial architecture knowledge publication](architecture-knowledge-v1.md).
`--json` emits the exact canonical snapshot bytes, suitable for explicit shell
redirection into a file consumed by `graph-snapshot`, `graph-view`, or paired
graph-supported assessment. `--quiet` emits nothing. The command validates the
packaged snapshot and its canonical initial graph-change proposal together
before use; missing, drifting, or invalid package assets are an internal
integrity failure. It writes nothing, is offline, and never dereferences source
locators.

### `archsift graph-snapshot <snapshot>`

Validates one published canonical architecture knowledge-graph snapshot file
beneath the current directory. The command checks the packaged graph schema,
typed node and relation semantics, assertion provenance, references, and both
addressing rules. It recomputes the immutable graph version and snapshot content
identity from the snapshot's own knowledge and refuses bytes that are not the
exact canonical serialization of that content.

Human output states the schema version, immutable graph version, snapshot
content identity, and total node and relation counts. `--json` additionally
reports counts for every declared node and relation kind. The command is
read-only and offline: it writes nothing, opens no network connection, and
treats every source locator as provenance data rather than a path or fetch
instruction.

Malformed or ambiguous JSON exits `10`; an unsupported graph schema version
exits `11`; a schema, semantic, provenance, reference, addressing, or canonical
serialization violation exits `12`. A path outside the current directory, an
unsafe path, or a non-regular-file target exits `13`; a missing or unreadable
file exits `14`.

### `archsift graph-change <proposal> <proposed-snapshot>` [`--base-snapshot` <base>]

Validates one canonical [graph-change proposal](graph-change-v1.md) against the
exact semantic delta between immutable snapshots. Initial publication omits a
base and permits additions only. Evolution requires `--base-snapshot` and exact
base/proposed schema, immutable graph-version, and content-identity references.

The validator reconstructs every node and relation delta by stable ID and
canonical entry content identity. It rejects omitted or invented changes,
unresolved or mismatched evidence sources, rationales that are not visible in
the proposed typed entry, false privacy/open-world attestations, and a behavior
change without both synthetic counterexample and regression-test IDs.

Human output reports only the change ID, exact base/proposed identities, and
added/changed/removed node/relation counts. `--json` emits the same deterministic
summary and `--quiet` emits nothing. The command safely reads regular contained
files, writes nothing, is fully offline, and never dereferences source locators.
Malformed or ambiguous input exits `10`; unsupported proposal or graph schema
exits `11`; contract, delta, evidence, or semantic failure exits `12`; unsafe
paths exit `13`; missing or unreadable files exit `14`. Diagnostics name
FR-014/FR-015.

### `archsift graph-view <snapshot> <request>`

Constructs one deterministic private task-relevant view from a canonical
published snapshot and a canonical private request, both regular files beneath
the current directory. Request schema version 1 is strict canonical JSON:

```json
{"bindings":[{"finding_id":"finding-agency","rule_id":"agency-necessity-rule"}],"finding_ids":["finding-agency"],"request_schema_version":1,"root_ids":["runtime-agency"]}
```

`root_ids` explicitly select reusable semantic identifiers relevant to the
bounded task. `finding_ids` are private case-scoped identifiers, and each
binding connects one of them to a reusable `decision-rule` node. ArchSift never
infers roots or bindings from topology or prose.

Human output reports the graph and case-view identities and the trace,
conflict, reusable-knowledge-gap, and private-finding counts without rendering
authored graph text. `--json` returns the canonical private view plus its
`case_view_content_identity`, including canonical content identities for the
reusable nodes and relations on complete finding-reaching paths; `--quiet`
returns only the exit status. The
command writes nothing and never changes assessment, verdicts, records, or
either input. The request and returned view remain private case material and
must never be merged into a public reusable snapshot.

Malformed or ambiguous JSON exits `10`; unsupported graph or request schema
versions exit `11`; non-canonical, structurally invalid, or semantically invalid
requests exit `12`; unsafe, escaping, or non-file paths exit `13`; and missing
or unreadable inputs exit `14`. Every diagnostic names its input, field,
FR-015, and remediation.

### `archsift usability-results <results>`

Validates one completed usability cohort result against the frozen
[human protocol](usability-check-v1.md) or the
[simulated protocol](usability-check-v2.md) and its privacy-bounded result
contract. Under protocol 1.0.0, a cohort of four or five passing sessions exits
`0` with status `criterion-met`; three or fewer pass with exit `12` and status
`criterion-not-met`. Under protocol 2.0.0, three or four passing simulated
sessions exit `0`; two or fewer pass with exit `12`; a duplicate agent product
across sessions is a contract error. Schema, binding, privacy, or contract
errors are not accepted cohort evidence.

### `archsift method-review-results <results>`

Validates one completed architecture-method review result against the frozen
[human protocol](method-review-v1.md) or the [simulated protocol](method-review-v2.md).
Under protocol 1.0.0, a single review that passes the four-example causal-trace contract
exits `0` with status `criterion-met`; a failing or incomplete review exits `12`.
Under protocol 2.0.0, three or four simulated sessions meeting the session criterion exit `0`;
two or fewer pass with exit `12`; a duplicate agent product across sessions is a contract error.
Every result declares its exact method, ruleset, and example-corpus binding. The packaged registry,
not version ordering, determines whether that combination was published. Current-binding output is
unchanged. A valid result for a registered superseded binding remains historical evidence: human
and JSON output name all three covered versions, JSON appends `-superseded` to the criterion status,
and every output mode returns exit `16` rather than current success. An unregistered binding exits
`11` with `method-review-binding-unsupported`.

## The case workspace and dossier

A case workspace is one self-contained directory:

```
my-case/
├── case.yaml      # the versioned dossier (schema version 1)
├── README.md      # human-readable workspace guidance
├── evidence/      # artefact bytes referenced by observed evidence
└── output/        # generated decision records (never hand-edited)
```

The dossier is human-editable YAML validated into typed domain models. It
identifies the case, declares its language, states the operational task boundary
(operation, start and completion conditions, actors, accountable owner, systems
and tools, information read, actions with approval boundaries, exclusions), and
covers up to four decision areas:

- **problem value** — desired outcome, current baseline, affected volume,
  material pain, error cost, and why technology may be the limiting factor;
- **agency necessity** — whether runtime model-directed control is necessary;
- **autonomy permission** — reversibility, blast radius, regulatory exposure,
  data confidence, accountability, auditability, human intervention, and safe
  degradation, with hard vetoes and mandatory human-control boundaries bound to
  the actions they constrain;
- **comparative fit** — candidates mapped to control classes, outcome and
  constraint tests, pairwise comparisons across eleven dimensions, and the
  evidence-backed strongest-simpler boundary.

Every material claim is recorded in the evidence ledger as one of four kinds:

| Kind | Meaning | Requires |
|---|---|---|
| `observed` | Backed by a named artefact or measurement | provenance, observation date |
| `assumption` | Believed but not yet verified | what would falsify it |
| `estimate` | Quantified or categorical forecast | method and owner |
| `missing` | Required evidence not yet available | what would resolve it |

Each evidence entry has a stable ID, an owner, the decision questions it
affects, and optional artefact references. Duplicate IDs and missing references
fail validation.

### The declared case language

`case.yaml` declares a `language` code, defaulting to `en` when the field is
omitted. English is the only supported language today. The code governs what
ArchSift itself generates — the `init` workspace guidance and every
decision-record report — and each report states the language it is written in.

An unknown or unsupported code fails closed rather than being ignored: a
malformed code is rejected by the schema, and a well-formed code ArchSift cannot
generate content in is rejected with a `language-unsupported` diagnostic naming
the supported set. Both exit `12`.

The code is part of the canonical dossier bytes the record is addressed by, so
changing the declared language produces a distinct record. Omitting the field
and declaring `en` are the same declaration and address the same record.

Writing a case's own prose and evidence in the declared language is a documented
convention, not a machine-verifiable fact. ArchSift never inspects authored text
to judge what language it is written in, so a mismatch between the declared code
and the prose is never reported as an error. Declaring a language states an
intent about the case; it never asserts a truth about its content.

## Decision records and sensitive-value masking

A decision record is immutable and content-addressed by the canonical dossier
bytes, the content identities of every cited evidence artefact, the ruleset,
configuration, and tool version, plus the exact graph and finding-relevant
entry identities when `graph_use` is present. Reassessing any changed input
creates a distinct record; rerunning identical inputs produces byte-identical
outputs.

Before serialising or persisting either representation, ArchSift applies a
deterministic, offline sensitive-value masking policy (policy v1) to every
authored string selected for output. The policy replaces only matched values
with fixed category placeholders, for:

- payment-card numbers that pass the Luhn check and a documented
  issuer-identification range;
- SSN- or ITIN-shaped values that pass documented area, group, and serial
  constraints, in the recognised separated format or under a strong label;
- credentials matching a documented token or key signature, or following a
  strong credential label such as `password`, `api_key`, `access_key`,
  `client_secret`, or `auth_token`;
- values following prose-ambiguous labels such as `secret`, `token`, or
  `credential` only when they match a documented credential shape.

A short ordinary word remains unmasked, and the policy is deliberately
high-precision rather than exhaustive: novel, unlabelled, obfuscated, or
prose-ambiguous sensitive values may remain. Both outputs identify that masking
was applied and warn that a record is **not guaranteed to be sensitive-data-free
and still requires handling appropriate to its source material**. Masking never
changes assessment, verdicts, evidence, or the content identities that address
the record; it transforms only emitted field values.

## Offline behaviour and exit codes

Every command runs without network access. Case content is untrusted data: the
tool never executes instructions, code, templates, or paths supplied by a
dossier, never dereferences source locators or URLs, and refuses any path that
would escape the case workspace unless explicitly granted.

See [exit-codes.md](exit-codes.md) for the stable exit-code contract, including
the distinct codes for malformed input, unsupported schema, validation failure,
unsafe paths, unavailable artefacts, persistence conflicts, and internal errors.
