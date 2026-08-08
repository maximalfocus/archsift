# ArchSift method specification 1.0.0

- **Method version:** `1.0.0`
- **Ruleset version:** `1.6.0`
- **Status:** normative for the listed ArchSift rules

This document makes the packaged ruleset reviewable without private requirements or case material. “Normative” means that this document explains ArchSift's own behavior. The cited public sources inform the design principles; they do not mandate ArchSift's exact classes, evidence categories, rule effects, thresholds, or verdicts.

## Scope and decision constitution

ArchSift assesses one bounded operational task against explicitly authored evidence and candidates. Its local decision constitution is:

1. Bound the task before choosing technology.
2. Decide problem value, agency necessity, autonomy permission, and comparative fit separately.
3. Compare represented candidates from least to most runtime freedom.
4. Keep hard vetoes and mandatory human controls explicit; never average them into a score.
5. Select the least complex surviving class only when no simpler represented class is undetermined.
6. Abstain when a potentially decisive fact lacks credible support.
7. Preserve every finding's rule, criterion, evidence IDs, effect, and consequence.

NIST AI RMF 1.0 informs the emphasis on contextual mapping, explicit risk information, measurement, documentation, accountability, and governance. NIST SP 800-30 Rev. 1 informs the treatment of uncertainty as part of a risk judgement rather than as evidence for a favorable conclusion. These sources do not prescribe ArchSift's ordered-elimination algorithm.

## Architecture classes

The classes are an ArchSift taxonomy ordered by increasing runtime execution freedom:

1. **`human-owned-work`:** people retain execution and decision control; tools may support the work but do not execute its decision path.
2. **`process-redesign`:** ownership, sequence, information flow, or controls change without introducing a new automation architecture for the bounded task.
3. **`deterministic-automation`:** software executes authored steps and branches; runtime behavior is selected by deterministic code rather than model-directed adaptation.
4. **`fixed-ai-workflow`:** code fixes orchestration and control flow while a model performs bounded steps; the model does not choose new tools or replan the workflow at runtime.
5. **`agentic-control`:** within an authored authority boundary, a model chooses tools or revises execution at runtime using environmental feedback.

A class label is not a recommendation. Only authored candidates are evaluated, and a simpler class can be selected only when a represented candidate in that class survives.

## Four separate decisions

- **Problem value:** whether the bounded task has measurable binding outcomes, baselines, and material constraints worth addressing.
- **Agency necessity:** whether credible structured evidence establishes fixed-workflow insufficiency and a need for runtime model-directed adaptation.
- **Autonomy permission:** which consequential task actions an automation candidate may control, subject to hard vetoes and mandatory human controls.
- **Comparative fit:** whether represented candidates credibly meet binding outcomes and constraints and face the required directional comparisons.

Evidence in one area cannot silently answer another. Business value does not grant autonomy; permission does not prove agency is needed; an agentic role label does not prove comparative superiority.

## Rule effects and precedence

| Effect | Meaning |
|---|---|
| `block` | The affected candidate is eliminated. |
| `require-evidence` | The affected candidate or assessment remains undetermined until the named material evidence gap is resolved. |
| `support-candidate` | The named criterion supports the candidate or verdict path but cannot offset a block or evidence gap. |
| `constrain-autonomy` | The candidate may remain eligible only with the named human control retained. |
| `non-decisive` | The fact is recorded explicitly but does not alter that candidate's disposition. |

For one candidate, `block` takes precedence over `require-evidence`; `require-evidence` takes precedence over support, constraint, and non-decisive findings. A represented class survives when any candidate in it survives, is undetermined when none survive and at least one is undetermined, and is eliminated only when all its candidates are eliminated. Ordered elimination considers classes from `human-owned-work` through `agentic-control`; an undetermined simpler class prevents promotion to a more complex survivor.

Verdicts then resolve as follows:

- `insufficient-evidence` when prerequisites or a potentially decisive class are undetermined;
- `conditional` when the minimum-sufficient class is determined but has authored class-neutral unmet conditions;
- `no-technology-change` when human-owned work or process redesign is minimum sufficient;
- `supported` when an evidence-complete automation class is minimum sufficient; and
- `no-permissible-candidate` when every represented class is eliminated by complete blocking evidence.

## Evidence truth boundary

ArchSift validates authored structure, references, provenance category, the presence of observed provenance or an estimate method, and deterministic rule consequences. It records exact evidence IDs and can bind referenced artefact bytes into a decision record. These checks do not prove external truth or operational adequacy.

ArchSift does **not** prove:

- that a claim is externally true, complete, representative, current, or operationally adequate;
- that an estimate method is statistically or scientifically sound;
- that an owner, reviewer, or source is trustworthy;
- that a candidate will perform as claimed in production;
- regulatory compliance, safety certification, or permission outside the authored boundary; or
- that the represented candidates exhaust all possible architectures.

An `assumption` or `known-gap` may remain visible but cannot establish a decisive fact. `observed` evidence needs authored provenance; an `estimate` needs an authored method. This is an ArchSift credibility boundary, not external verification. W3C PROV-O informs the explicit provenance model, while NIST AI RMF informs documentation and measurement; neither source certifies dossier claims.

## Current behavior and explicit limits

- Unknown decisive answers and missing required sections produce `require-evidence`, not a favorable inference.
- Assumption-only candidate failure cannot eliminate a simpler candidate and promote complexity.
- A credible binding outcome or constraint failure blocks the affected candidate; support on another criterion cannot offset it.
- Active overlapping hard vetoes block prohibited automation classes. Unknown veto status or applicability leaves affected candidates undetermined.
- Applicable mandatory human controls must be retained. Retention constrains the architecture; omission blocks it.
- Agentic control survives agency rules only when a fixed workflow is credibly insufficient, at least one credible residual case records that insufficiency, runtime tool choice or replanning is credibly required, and environmental feedback is credibly available.
- A sufficient fixed workflow, no runtime adaptation need, or unavailable environmental feedback blocks agentic control. Other known agency facts may support the trace or remain non-decisive without changing that contract.
- Findings are deterministic over validated structured fields. Rationale, descriptions, and residual-case prose are inert and are not parsed into conclusions.

ArchSift currently validates local structural coherence and applies the listed rules. It does **not** yet implement general pairwise or cross-section contradiction diagnostics, prove that a `strongest-simpler` role is substantively strongest, or discover unrepresented alternatives. Those capabilities must not be inferred from this specification.

## Public rationale sections

<a id="bounded-task"></a>
### `method-v1.0.0#bounded-task`

A broad use-case label does not define an assessable architecture boundary. ArchSift requires an operation, trigger, completion condition, accountable owner, actors, information, actions, approval boundaries, and exclusions before assessment. This is an ArchSift design choice informed by the AI RMF's direction to map context and intended purposes before measuring or managing risk.

**Sources:** `nist-ai-rmf-1.0`.

<a id="problem-value"></a>
### `method-v1.0.0#problem-value`

Technology selection must be anchored to at least one measurable binding outcome and a resolvable, credibly supported baseline. Missing value facts cause abstention rather than allowing architecture enthusiasm to substitute for a defined problem. The exact required fields and evidence threshold are ArchSift choices informed by contextual risk mapping and explicit risk-assessment inputs.

**Sources:** `nist-ai-rmf-1.0`, `nist-sp-800-30r1`.

<a id="separate-decisions"></a>
### `method-v1.0.0#separate-decisions`

Problem value, agency necessity, autonomy permission, and comparative fit answer different questions and remain separately inspectable. ArchSift does not treat usefulness as permission, permission as necessity, or a candidate role as comparative proof. This separation is a local safeguard informed by public principles for contextual risk management, transparency, accountability, and human-centered values.

**Sources:** `nist-ai-rmf-1.0`, `oecd-ai-principles-2024`.

<a id="credible-evidence"></a>
### `method-v1.0.0#credible-evidence`

A decisive fact requires at least one observed source with provenance or an estimate with an authored method. Assumptions and known gaps are preserved but cannot establish the fact. Evidence IDs must remain traceable to the occurrence that used them. This threshold is an ArchSift policy informed by provenance and documented measurement practices; it does not validate source truth or method quality.

**Sources:** `nist-ai-rmf-1.0`, `w3c-prov-o-2013`.

<a id="candidate-comparison"></a>
### `method-v1.0.0#candidate-comparison`

Each represented candidate must test every binding outcome and constraint, and required comparison roles and directional comparisons must be explicit. Unknown or unsupported tests remain undetermined. Roles organize the decision boundary but never identify a winner. ArchSift's exact comparison schema is a local design informed by documented contextual analysis and explicit uncertainty in risk assessment.

**Sources:** `nist-ai-rmf-1.0`, `nist-sp-800-30r1`.

<a id="agency-necessity"></a>
### `method-v1.0.0#agency-necessity`

Greater runtime model freedom requires more than the presence of a model or a complicated workflow. ArchSift requires credible fixed-workflow insufficiency, a concrete residual case, runtime tool choice or replanning, and available environmental feedback. Monitorability facts remain visible but do not prove necessity or permission. This survival contract is an ArchSift design choice informed by AI risk-management guidance concerning context, human-AI configurations, measurement, and generative-AI risk; the cited sources do not define ArchSift's `agentic-control` class.

**Sources:** `nist-ai-600-1`, `nist-ai-rmf-1.0`.

<a id="autonomy-boundaries"></a>
### `method-v1.0.0#autonomy-boundaries`

Automation candidates must declare which consequential task actions they control. Active vetoes and mandatory human controls bind only where their authored action scope applies. Unknown status, applicability, authority, or support leaves a candidate undetermined; a proven prohibited overlap or omitted mandatory control blocks it. ArchSift's rule mechanics are local choices informed by risk governance, accountability, human oversight, least-privilege, and auditability principles.

**Sources:** `nist-ai-rmf-1.0`, `nist-sp-800-53r5`, `oecd-ai-principles-2024`.

<a id="ordered-elimination"></a>
### `method-v1.0.0#ordered-elimination`

Candidate findings are criterion-specific and non-scoring. Credible failure of any binding outcome or constraint eliminates the candidate; credible success supports it without offsetting a block. Missing decisive evidence leaves it undetermined. ArchSift then selects the least complex represented surviving class only after simpler represented classes are conclusively eliminated. The algorithm is an ArchSift design informed by explicit risk criteria and uncertainty handling, not prescribed by the cited sources.

**Sources:** `nist-ai-rmf-1.0`, `nist-sp-800-30r1`.

<a id="verdict-resolution"></a>
### `method-v1.0.0#verdict-resolution`

ArchSift distinguishes a supported minimum-sufficient class, a determined class with class-neutral conditions, a positive no-technology-change outcome, complete evidenced elimination, and abstention caused by potentially decisive uncertainty. Missing evidence never promotes a more complex class. These verdict semantics are ArchSift choices informed by documented risk decisions and explicit uncertainty.

**Sources:** `nist-ai-rmf-1.0`, `nist-sp-800-30r1`.

## Rule-to-rationale index

This table is normative for ruleset `1.6.0`. It is sorted by immutable rule ID.

| Rule ID | Rationale ID | Public source IDs |
|---|---|---|
| `active-veto-applicability-missing` | `method-v1.0.0#autonomy-boundaries` | `nist-ai-rmf-1.0`, `nist-sp-800-53r5`, `oecd-ai-principles-2024` |
| `active-veto-blocks-candidate` | `method-v1.0.0#autonomy-boundaries` | `nist-ai-rmf-1.0`, `nist-sp-800-53r5`, `oecd-ai-principles-2024` |
| `agency-answer-unknown` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agency-necessity-missing` | `method-v1.0.0#separate-decisions` | `nist-ai-rmf-1.0`, `oecd-ai-principles-2024` |
| `agentic-agency-answer-unknown` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agentic-agency-fact-non-decisive` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agentic-agency-necessity-missing` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agentic-credible-agency-evidence-missing` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agentic-credible-residual-evidence-missing` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agentic-dynamic-execution-supports-agency` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agentic-feedback-supports-agency` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agentic-feedback-unavailable-blocks-candidate` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agentic-fixed-workflow-insufficiency-supports-agency` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agentic-fixed-workflow-sufficient-blocks-candidate` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agentic-residual-case-missing` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agentic-residual-case-supports-agency` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agentic-runtime-adaptation-missing` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `agentic-runtime-adaptation-supports-agency` | `method-v1.0.0#agency-necessity` | `nist-ai-600-1`, `nist-ai-rmf-1.0` |
| `automation-authority-missing` | `method-v1.0.0#autonomy-boundaries` | `nist-ai-rmf-1.0`, `nist-sp-800-53r5`, `oecd-ai-principles-2024` |
| `autonomy-answer-unknown` | `method-v1.0.0#autonomy-boundaries` | `nist-ai-rmf-1.0`, `nist-sp-800-53r5`, `oecd-ai-principles-2024` |
| `autonomy-boundary-non-decisive` | `method-v1.0.0#autonomy-boundaries` | `nist-ai-rmf-1.0`, `nist-sp-800-53r5`, `oecd-ai-principles-2024` |
| `autonomy-permission-missing` | `method-v1.0.0#separate-decisions` | `nist-ai-rmf-1.0`, `oecd-ai-principles-2024` |
| `baseline-reference-unresolved` | `method-v1.0.0#problem-value` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `binding-constraint-failed` | `method-v1.0.0#ordered-elimination` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `binding-constraint-met` | `method-v1.0.0#ordered-elimination` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `binding-outcome-failed` | `method-v1.0.0#ordered-elimination` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `binding-outcome-met` | `method-v1.0.0#ordered-elimination` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `binding-outcome-missing` | `method-v1.0.0#problem-value` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `candidate-comparison-missing` | `method-v1.0.0#separate-decisions` | `nist-ai-rmf-1.0`, `oecd-ai-principles-2024` |
| `candidate-constraint-test-missing` | `method-v1.0.0#candidate-comparison` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `candidate-outcome-test-missing` | `method-v1.0.0#candidate-comparison` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `candidate-problem-value-missing` | `method-v1.0.0#separate-decisions` | `nist-ai-rmf-1.0`, `oecd-ai-principles-2024` |
| `candidate-role-incompatible` | `method-v1.0.0#candidate-comparison` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `candidate-test-result-unknown` | `method-v1.0.0#candidate-comparison` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `comparison-result-unknown` | `method-v1.0.0#candidate-comparison` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `credible-agency-evidence-missing` | `method-v1.0.0#credible-evidence` | `nist-ai-rmf-1.0`, `w3c-prov-o-2013` |
| `credible-authority-evidence-missing` | `method-v1.0.0#credible-evidence` | `nist-ai-rmf-1.0`, `w3c-prov-o-2013` |
| `credible-autonomy-evidence-missing` | `method-v1.0.0#credible-evidence` | `nist-ai-rmf-1.0`, `w3c-prov-o-2013` |
| `credible-baseline-missing` | `method-v1.0.0#credible-evidence` | `nist-ai-rmf-1.0`, `w3c-prov-o-2013` |
| `credible-candidate-test-evidence-missing` | `method-v1.0.0#credible-evidence` | `nist-ai-rmf-1.0`, `w3c-prov-o-2013` |
| `credible-comparison-evidence-missing` | `method-v1.0.0#credible-evidence` | `nist-ai-rmf-1.0`, `w3c-prov-o-2013` |
| `credible-hard-veto-evidence-missing` | `method-v1.0.0#credible-evidence` | `nist-ai-rmf-1.0`, `w3c-prov-o-2013` |
| `credible-human-control-evidence-missing` | `method-v1.0.0#credible-evidence` | `nist-ai-rmf-1.0`, `w3c-prov-o-2013` |
| `credible-residual-case-evidence-missing` | `method-v1.0.0#credible-evidence` | `nist-ai-rmf-1.0`, `w3c-prov-o-2013` |
| `hard-veto-status-unknown` | `method-v1.0.0#autonomy-boundaries` | `nist-ai-rmf-1.0`, `nist-sp-800-53r5`, `oecd-ai-principles-2024` |
| `mandatory-human-control-omitted` | `method-v1.0.0#autonomy-boundaries` | `nist-ai-rmf-1.0`, `nist-sp-800-53r5`, `oecd-ai-principles-2024` |
| `mandatory-human-control-retained` | `method-v1.0.0#autonomy-boundaries` | `nist-ai-rmf-1.0`, `nist-sp-800-53r5`, `oecd-ai-principles-2024` |
| `overlapping-veto-status-unknown` | `method-v1.0.0#autonomy-boundaries` | `nist-ai-rmf-1.0`, `nist-sp-800-53r5`, `oecd-ai-principles-2024` |
| `problem-value-missing` | `method-v1.0.0#problem-value` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `required-candidate-role-missing` | `method-v1.0.0#candidate-comparison` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `required-comparison-missing` | `method-v1.0.0#candidate-comparison` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `task-boundary-missing` | `method-v1.0.0#bounded-task` | `nist-ai-rmf-1.0` |
| `verdict-conditional` | `method-v1.0.0#verdict-resolution` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `verdict-insufficient-evidence` | `method-v1.0.0#verdict-resolution` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `verdict-no-permissible-candidate` | `method-v1.0.0#verdict-resolution` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `verdict-no-technology-change` | `method-v1.0.0#verdict-resolution` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |
| `verdict-supported` | `method-v1.0.0#verdict-resolution` | `nist-ai-rmf-1.0`, `nist-sp-800-30r1` |

## Public source registry

All sources below are primary publications from the named standards body or intergovernmental organization. They inform the associated rationale; none is represented as requiring an ArchSift-specific rule.

### `nist-ai-600-1`

- **Title:** *Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile*
- **Publisher:** National Institute of Standards and Technology
- **Version/date:** NIST AI 600-1, July 2024
- **URL:** https://doi.org/10.6028/NIST.AI.600-1

### `nist-ai-rmf-1.0`

- **Title:** *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*
- **Publisher:** National Institute of Standards and Technology
- **Version/date:** NIST AI 100-1, January 2023
- **URL:** https://doi.org/10.6028/NIST.AI.100-1

### `nist-sp-800-30r1`

- **Title:** *Guide for Conducting Risk Assessments*
- **Publisher:** National Institute of Standards and Technology
- **Version/date:** NIST SP 800-30 Rev. 1, September 2012
- **URL:** https://doi.org/10.6028/NIST.SP.800-30r1

### `nist-sp-800-53r5`

- **Title:** *Security and Privacy Controls for Information Systems and Organizations*
- **Publisher:** National Institute of Standards and Technology
- **Version/date:** NIST SP 800-53 Rev. 5, September 2020; updated December 2020
- **URL:** https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final

### `oecd-ai-principles-2024`

- **Title:** *Recommendation of the Council on Artificial Intelligence*
- **Publisher:** Organisation for Economic Co-operation and Development
- **Version/date:** OECD/LEGAL/0449, adopted 2019; amended 2024
- **URL:** https://legalinstruments.oecd.org/en/instruments/OECD-LEGAL-0449

### `w3c-prov-o-2013`

- **Title:** *PROV-O: The PROV Ontology*
- **Publisher:** World Wide Web Consortium
- **Version/date:** W3C Recommendation, 30 April 2013
- **URL:** https://www.w3.org/TR/2013/REC-prov-o-20130430/

## Rule-change governance

The method and ruleset are versioned separately because public explanation can improve without changing decision behavior.

- Rule IDs are immutable and must never be repurposed. Removing or replacing a rule leaves its historical definition available under the recorded ruleset version.
- Any normative change to a rule's effect, requirement, description, consequence, source rationale, applicability, precedence, or evaluation behavior requires a new ruleset version, a new method version that names it, updated mappings, tests, and compatibility review.
- A method **major** version changes the decision constitution or interpretation incompatibly; a **minor** version adds compatible normative explanation or source coverage; a **patch** corrects citation metadata or clarifies text without changing rule behavior.
- Citation corrections alone do not justify a ruleset-version change. They produce a new immutable method file and mapping metadata while leaving the associated historical method file available.
- The method version and its declared ruleset version must match the packaged metadata. Every packaged rule must map exactly once; every source ID must resolve locally; mapping order is canonical.
- Tests and builds validate local identifiers and packaged assets only. Runtime evaluation and `archsift rules` never fetch or open citation URLs.
- Decision records bind the ruleset version and rule behavior. Historical method files preserve the public explanation for that version so existing records remain interpretable even after later method or ruleset releases.

A contributor proposing a normative change must explain why the existing rule is insufficient, identify the affected rule IDs and records, update the public rationale and citations, add acceptance-boundary tests, and avoid presenting an informing source as an external mandate for ArchSift's local design.
