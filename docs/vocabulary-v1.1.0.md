# ArchSift plain-language vocabulary 1.1.0

- **Vocabulary version:** `1.1.0`
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

## Governance

- Coverage is total: every verdict, evidence state, control class,
  evidence-entry kind, finding effect, decision area, and packaged rule has
  exactly one entry, and the test suite proves it against the live
  enumerations and rule catalog.
- A wording change is a new vocabulary version. It addresses rendered outputs
  together with the record identity; it is never part of the record identity
  and never appears as a cause of a verdict change.
- Adding a rule to the ruleset requires adding its phrases in the same change.
