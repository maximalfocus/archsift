# ArchSift plain-language vocabulary 1.2.0

- **Vocabulary version:** `1.2.0`
- **Framework version:** `1.0.0` (the decision framework card, below)
- **Applies to:** every reader-facing output ArchSift generates
- **Inspect it with:** `archsift rules --json` (the `vocabulary` block) or `archsift rules`

ArchSift raises flags that a person reads; it does not verify, approve, reject,
or certify anything. This document is the published mapping from every
internal term a reader-facing output can present to one reader-facing phrase
in that neutral register. It is a rendering input: changing it produces a
distinct rendered output and never changes a decision record, its content
identity, or a verdict.

## Register

Reader-facing text describes what the rules found as flags on options, never
as an act of the tool upon the case. The words below, and their inflections,
do not appear in any vocabulary phrase, and a phrase that contains one fails
closed when the vocabulary loads:

`verify` `validate` `approve` `reject` `certify` `recommend` `veto`

An authored name or description may still contain such a word where it
describes the business process (a step a person approves); the exclusion
governs the vocabulary and the generated prose around authored text, not the
author's own words.

## Flags

| Finding effect | Flag | Meaning |
|---|---|---|
| `block` | stop | The option cannot be the indicated option under the rules. |
| `require-evidence` | gap | Material evidence is missing; the option stays open until it is recorded. |
| `constrain-autonomy` | condition | The option stays open only with the named person-required step kept. |
| `support-candidate` | fit | The evidence supports the option on this point; it never outweighs a stop or a gap. |
| `non-decisive` | noted | Recorded for completeness; it does not change the option's standing. |

Flags are never counted or totalled. One stop flag outweighs any number of fit
flags.

## The result and the indicated option

The verdict renders as **the result**. The minimum-sufficient option determined
by ordered elimination renders as **the indicated option**, always together
with the statement that the decision rests with the accountable owner.

| Verdict token | Reader-facing phrase |
|---|---|
| `supported` | the evidence indicates the least complex option that meets every requirement |
| `conditional` | the evidence indicates an option, subject to named conditions |
| `insufficient-evidence` | more evidence is needed before an option can be indicated |
| `no-permissible-candidate` | no represented option meets the required outcomes and constraints |
| `no-technology-change` | the evidence indicates keeping the work with people or redesigning the process, with no new technology |

| Evidence state | Reader-facing phrase |
|---|---|
| `evidence-complete` | the evidence needed for this result is complete |
| `evidence-incomplete` | material evidence is still missing |

## The four questions and the five options

| Decision area | Question |
|---|---|
| `problem-value` | Is there a problem worth solving? |
| `agency-necessity` | Must a model choose the steps at run time? |
| `autonomy-permission` | Which actions may be handed over, and which must a person keep? |
| `comparative-fit` | Which option fits best against the simpler alternatives? |

| Control class | Option |
|---|---|
| `human-owned-work` | people do the work |
| `process-redesign` | redesign the process first |
| `deterministic-automation` | rule-based automation |
| `fixed-ai-workflow` | AI inside a fixed workflow |
| `agentic-control` | AI that chooses its own steps |

| Evidence-entry kind | Reader-facing phrase |
|---|---|
| `observed` | seen and recorded |
| `assumption` | assumed |
| `estimate` | estimated |
| `missing` | not yet available |

## Structured questions, dimensions, roles, results, and states

The narrative also names the sixteen run-time and hand-over questions, the
eleven comparison dimensions, the four comparison roles, test and comparison
results, yes/no/unknown answers, stop-condition and condition states, evidence
authors, target kinds, and class dispositions by fixed phrases. They are
emitted under `question_fields`, `dimensions`, `roles`, `test_results`,
`comparison_results`, `answers`, `stop_condition_states`, `condition_states`,
`authors`, `target_kinds`, and `dispositions` in `archsift rules --json`.

## Rules

Every packaged decision rule maps to a reader-facing message template, a
consequence, and a remediation. A template names authored elements by
placeholder — `{candidate}`, `{outcome}`, `{constraint}`, `{criterion}`,
`{question}`, `{condition}`, `{control}`, `{boundary}`, `{residual}`,
`{comparator}`, `{dimension}`, `{role}`, `{conditions}` — which a rendering
resolves to the element's authored name or description, never to its
identifier. The complete rule table is emitted by `archsift rules --json`
under `vocabulary.rules` and is the normative form; a rule without phrases
fails closed at rendering.

## The decision framework card

The card is the ruleset read at one sitting (FR-020). It is a rendering of the
ruleset and the vocabulary, never a second ruleset: assessment runs the full
ruleset against the full dossier, and the card never participates in
evaluation, presents no score, total, weight, or case-specific ranking, and
states no rule the ruleset does not contain. It is emitted by
`archsift rules --json` under `vocabulary.framework` and printed by
`archsift rules`, and it is addressed by the ruleset version, the vocabulary
version, and the framework version.

The card contains, and only contains, in this order:

1. the four questions, each by its fixed name (above) and one plain sentence;
2. the five options, from least to most run-time freedom, each by its fixed
   name (above) and one plain sentence;
3. the five flags, each with its meaning (above);
4. the numbered framework rules, grouped under the question they serve or
   under how the result follows from the flags;
5. the statement: *Flags are not counted or totalled. A stop flag is never
   offset by fit flags. The decision rests with the accountable owner.*
6. the framework version.

### Framework rules (framework 1.0.0)

| # | Serves | Rule |
|---|---|---|
| 1 | Is there a problem worth solving? | Until the case records a bounded task, measurable required outcomes with today's baseline, and the four value statements, a gap flag is raised on the options as a whole. |
| 2 | Is there a problem worth solving? | An option that credibly does not reach a required outcome or does not meet a required constraint carries a stop flag; one that credibly does carries a fit flag; a test with no recorded result or without acceptable evidence carries a gap flag. |
| 3 | Must a model choose the steps at run time? | Every run-time question, and every case a fixed sequence cannot handle, must have a known answer with acceptable evidence; otherwise a gap flag is raised. |
| 4 | Must a model choose the steps at run time? | The option in which AI chooses its own steps carries a stop flag when a fixed sequence of steps is credibly sufficient, when no run-time tool choice or replanning is needed, or when the environment gives no feedback; it carries a fit flag when the evidence credibly shows the opposite. |
| 5 | Which actions may be handed over, and which must a person keep? | Every hand-over question, absolute stop condition, person-required step, and claim of authority over an action must be recorded with a known answer or status and acceptable evidence; otherwise a gap flag is raised. |
| 6 | Which actions may be handed over, and which must a person keep? | An option that would act where an absolute stop condition is in force, or that drops a person-required step, carries a stop flag; an option that keeps the step carries a condition flag. |
| 7 | Which option fits best against the simpler alternatives? | The options must include today's way of working, the strongest simpler alternative, and the proposal, each in its place; a missing option, role, boundary, or comparison raises a gap flag. |
| 8 | Which option fits best against the simpler alternatives? | A comparison with no recorded result, without acceptable evidence, or contradicting its counterpart raises a gap flag, unless every admissible value leaves the result unchanged, which is noted. |
| 9 | How the result follows from the flags | Options are read in order from least to most run-time freedom; when every gap is settled, the least free option that carries no stop flag is the indicated option, subject to any condition flags it carries. |
| 10 | How the result follows from the flags | While a gap flag remains on an option that could still be indicated, or on the options as a whole, the result is that more evidence is needed. |
| 11 | How the result follows from the flags | When every option carries a stop flag, no option can be indicated. |

At most twelve framework rules may exist; exceeding twelve is a method-design
decision that requires a PRD change.

### Rule mapping

Every packaged internal rule maps to exactly one framework rule, and every
framework rule maps to at least one internal rule. The mapping is emitted under
`vocabulary.framework.mapping`, is validated when the vocabulary loads (an
unmapped rule, a framework rule with no internal rule, or a thirteenth rule
fails closed), and is printed beside each rule by `archsift rules` as
`Framework rule <n>`. Adding an internal rule requires mapping it to an existing
framework rule or adding a framework rule in the same change. A framework rule
number is reader-facing vocabulary: reports may cite it; only a traceability
appendix names the internal rule identifier.

## Governance

- Coverage is total: every verdict, evidence state, control class,
  evidence-entry kind, finding effect, decision area, and packaged rule has
  exactly one entry, and the test suite proves it against the live
  enumerations and rule catalog.
- A wording change is a new vocabulary version. It addresses rendered outputs
  together with the record identity; it is never part of the record identity
  and never appears as a cause of a verdict change.
- Adding a rule to the ruleset requires adding its phrases and its framework
  rule mapping in the same change.
- Framework rule numbers are stable within a framework version; a renumbering
  or a change of a rule's sentence is a new framework version.
