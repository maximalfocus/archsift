# Independent simulated architecture-method review protocol 2.0.0

This protocol supersedes protocol 1.0.0 for the initial-release method-validation gate. It freezes a
reproducible check of whether ArchSift's public judgement trace connects each required decision
area to candidate disposition and verdict resolution, executed by independent simulated review
sessions. Protocol 1.0.0 remains frozen for human architect reviews and stays supported by the
validator.

Two simulated review cohorts have been run. The current committed result is
[`method-review-results.json`](../method-review-results.json) (cohort date 2026-08-15, source
commit `38dc9a9388c1b7e778dbc07c580d6420bab4302e`). `archsift method-review-results
method-review-results.json` exits `0` with `criterion-met`: three of four sessions met the
session criterion, applying the clarified classification rule for examples with no agentic or
automation candidate. The first cohort, bound to commit `75fb242e2207486dd52cd356f07966dc86790f6c`
under the prior protocol text, is preserved as an honest historical record at
[`method-review-results-1-criterion-not-met.json`](../method-review-results-1-criterion-not-met.json)
(exit `12`, `criterion-not-met`). The evidence of both cohorts is simulated: sessions were
executed by distinct agent products, and no claim that a human architect passed is made. Any later
cohort is a new result record bound to its own source commit.

## Success criterion

Run exactly four independent simulated review sessions, each executed by a distinct agent product,
against the same ArchSift source commit. Record the full 40-character lowercase commit ID. A
session passes only when its review of the fixed corpus meets the per-session criterion below with
no maintainer intervention. The cohort meets the criterion only when at least three of the four
sessions pass.

Do not replace, repeat, or rewrite a completed session to improve the cohort result. A later cohort
is a new result record bound to its own source commit.

## Bound versions and fixed corpus

Each session reviews packaged ArchSift 0.1.0 or a public ArchSift source commit, recorded as its
full 40-character commit ID, with method 1.2.0, ruleset 1.8.0, and public example corpus 1.0.0. The
result binds the exact supported version or full source commit used for assessment and the content
identity of each locally generated decision record. Other packaged versions require a later
protocol even if their method metadata happens to match.

The fixed corpus is the four entries in [`examples/manifest.json`](../examples/manifest.json), each
reviewed exactly once per session:

- `agentic-control`
- `fixed-workflow`
- `insufficient-evidence`
- `no-technology-change`

The corpus consists only of those maintained fictional example sources and their decision records
generated locally during the review. Generated JSON and Markdown records are review inputs, not
maintained source, and must not be committed.

## Session and independence requirements

A session is one agent product (e.g., a specific CLI agent harness with a specific model) started
fresh for this cohort. Record the agent product, model identifier, and harness version for each
session so the cohort is reproducible.

A session is ineligible if the agent has previously reviewed a completed result for this protocol,
authored the protocol, method, or any corpus example, or can use private project planning, private
discussions, or hidden task context — for example, a session continuing from a conversation in
which this protocol or the product's requirements were authored. Each of the four sessions uses a
different agent product; a second session with the same product is not an independent session.

The session starts with:

- a clean public ArchSift source checkout at the recorded commit;
- a fresh supported CPython environment;
- ArchSift installed from that checkout or from the matching built wheel;
- empty generated-output directories in the four example workspaces; and
- an empty local directory for review notes that will not be committed.

Permitted materials are public and version-bound: the root and example READMEs, CLI help, the
packaged method specification, `archsift rules` output, the exit-code documentation, the example
manifest and sources, and records generated from the fixed corpus. General terminal, JSON, and
architecture-review references are permitted. Source tests may be used only to reproduce a tool
failure after the reviewer has recorded the affected trace outcome; they are not review evidence.
Private repositories, unpublished results, hidden task context, and maintainer interpretations are
not permitted.

After the session starts, any tailored hint, interpretation, correction, trace classification,
record edit, command, or answer from a maintainer or moderator is **maintainer intervention**. A
session with intervention cannot meet the criterion. A moderator may silently observe and resolve a
safety or infrastructure emergency, but records intervention if that resolution helps complete the
review.

## Reproduce the public inputs

From the clean checkout, record the installed ArchSift version or commit and run:

```bash
archsift rules --json
archsift validate examples/agentic-control --json
archsift assess examples/agentic-control --json
archsift validate examples/fixed-workflow --json
archsift assess examples/fixed-workflow --json
archsift validate examples/insufficient-evidence --json
archsift assess examples/insufficient-evidence --json
archsift validate examples/no-technology-change --json
archsift assess examples/no-technology-change --json
```

Every command must complete offline. Record each decision record's `record_content_identity` and
verify its method/ruleset context against the bound public rules catalog and specification. Do not
change an example or rerun it with revised evidence to improve the review outcome.

## Four-area trace review

For each example, inspect problem value, agency necessity, autonomy permission, and comparative
fit exactly once. Use the dossier snapshot, `assessment.prerequisite_evaluation`,
`assessment.ordered_elimination_evaluation`, candidate dispositions, `verdict_rule_id`, and the
public rule-to-rationale catalog.

For each decision area:

1. Identify the exact authored evidence IDs and public rule IDs that expose the area's applicable
   decision-critical facts, including evidence gaps.
2. Follow the rule effect into a candidate disposition, a prerequisite that controls assessment,
   or the final verdict rule.
3. Record bounded candidate IDs and/or the verdict rule ID that terminate the trace. An
   explicitly non-decisive area still records the bounded candidate context whose disposition the
   fact does not alter, and/or the verdict rule that resolves the example. A recorded verdict rule
   must be one of the packaged `verdict-*` rules exposed by `archsift rules`.
4. Classify the outcome using exactly one of these values:
   - **`causal`:** at least one rule in the area's own `rule_ids` has a decision-affecting effect
     that participates in a prerequisite, candidate disposition, class ordering, or verdict.
   - **`explicitly-non-decisive`:** every rule in the area's `rule_ids` is a packaged
     `non-decisive` rule and explains why the fact does not alter disposition; a decision-affecting
     rule cannot be cited in the same trace.
   - **`display-only`:** the area's facts are visible, but neither a causal nor an explicitly
     non-decisive trace can be completed.

"Visible" and "not applicable" are not passing substitutes. When an area has no applicable causal
or explicitly non-decisive rule, record `display-only`; do not infer an unstated method rule. An
example passes only when all four areas are `causal` or `explicitly-non-decisive`.

When no agentic candidate is represented, the packaged non-decisive agency rule
(`agentic-agency-fact-non-decisive`) explains that the agency facts do not alter any disposition;
the assessment emits it as a dossier-level finding. When no automation candidate is represented,
the packaged non-decisive boundary rule (`autonomy-boundary-non-decisive`) likewise explains the
autonomy facts. In those cases the area may be classified `explicitly-non-decisive` citing the
non-decisive rule alone; a decision-affecting rule may not be cited in the same trace.

This review checks the transparency and completeness of the declared judgement trace. It does not
re-decide the example, prescribe an expected architecture, establish that authored evidence is
externally true, or certify operational, regulatory, safety, or security adequacy.

## Disagreement taxonomy and per-session criterion

Record every disagreement once with its corpus example, decision area, decision-critical state,
and exactly one trace class:

- **`declared-evidence`:** the disagreement is with an authored claim and cites only evidence IDs
  recorded in that area's trace.
- **`public-rule`:** the disagreement is with ArchSift's normative method and cites only packaged
  rule IDs recorded in that area's trace.
- **`product-gap`:** neither the evidence nor a public rule explains the behavior; record a bounded
  pseudonymous `gap-*` ID for a separate public-safe product-gap workflow.
- **`unclassified`:** the reviewer cannot trace the disagreement to any of the preceding classes.

An unclassified disagreement fails the session criterion. A decision-critical product gap fails
the session criterion even though it is correctly recorded; it must not be silently converted into
a rule or evidence disagreement. A non-decision-critical product gap remains visible but does not
by itself fail this protocol.

A session meets its criterion only when:

- all four fixed examples and all four decision areas per example are present exactly once;
- no decision area is `display-only`;
- no disagreement is unclassified;
- no decision-critical product gap is present; and
- no maintainer intervention occurred.

The cohort criterion is met only when at least three of the four sessions meet their session
criterion.

## Result record and offline validation

Record the cohort in one JSON file conforming to the packaged simulated-cohort result schema
(schema version 2). The record binds the protocol version and the tested full 40-character
lowercase source commit; contains exactly four sessions, each with a unique pseudonymous session
ID, agent product, model identifier, and harness version; and for each session carries the fixed
corpus IDs, locally generated record identities, bounded rule/evidence/candidate and verdict
references per decision area, classified disagreements, intervention state, derived example and
session outcomes, and enumerated failure reasons. Do not record a name, contact detail, employer,
free-form review narrative, transcript, terminal history, private case content, internal URL,
private path, or hidden evidence. A product-gap ID is a pointer for later public-safe issue work,
not a container for case or participant information.

Validate the completed record locally with the exact command:

```bash
archsift method-review-results method-review-results.json
```

The validator reads only the named local JSON file and packaged public schema/rule metadata. It
uses no network, telemetry, model service, private repository, or generated decision record. Exit
code `0` means the record is internally valid and at least three of exactly four sessions meet the
session criterion; any other exit code means a version/contract error or a criterion failure.
`--json` provides deterministic structured diagnostics, and `--quiet` emits only the process exit
code. Protocol 1.0.0 single-reviewer results continue to validate under their own semantics.
