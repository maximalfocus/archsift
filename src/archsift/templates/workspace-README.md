# ArchSift case workspace

This directory contains one local architecture-decision case.

- `case.yaml` is the versioned, human-editable dossier.
- `evidence/` is reserved for local evidence artefacts; ledger provenance is inert metadata and validation does not open it.
- `output/` is reserved for generated decision records and is safe to recreate.

Add one operational `task` only after its boundary is known. A programme name is not enough: record observable start and completion conditions, participants, inputs, produced actions, approval boundaries, and explicit exclusions.

```yaml
task:
  operation: Review one submitted application and produce a disposition.
  starts_when: A complete application enters the review queue.
  completes_when: The disposition and rationale are recorded for the applicant.
  accountable_owner: Review operations lead
  actors: [Case reviewer, Quality approver]
  systems_and_tools: [Application register, Policy search]
  information_read: [Submitted application, Current policy, Prior decisions]
  actions:
    - id: draft-disposition
      description: Draft a disposition and supporting rationale.
      consequential: false
      approval_boundary: A case reviewer may draft; no external release occurs.
    - id: release-disposition
      description: Release the approved disposition to the applicant.
      consequential: true
      approval_boundary: A quality approver must approve before release.
  exclusions:
    - Changing policy
    - Executing downstream enforcement
```

The `evidence` ledger keeps observed facts distinct from assumptions, estimates, and known gaps. Every entry needs a stable ID, owner, claim, and affected decision area. Use only the metadata required by its kind:

```yaml
evidence:
  - id: baseline-observation
    kind: observed
    claim: The current task takes 12 minutes at the measured median.
    owner: Process analyst
    affects: [problem-value]
    provenance: evidence/sanitised-baseline.csv
    observed_at: 2026-08-06
  - id: volume-assumption
    kind: assumption
    claim: Monthly demand will remain near its current level.
    owner: Product lead
    affects: [problem-value, comparative-fit]
    falsified_by: A three-month demand sample differs by more than 20 percent.
  - id: workflow-estimate
    kind: estimate
    claim: A fixed workflow would handle most routine cases.
    owner: Engineering lead
    affects: [agency-necessity, comparative-fit]
    method: Estimate from a sanitised representative-case sample.
  - id: exception-gap
    kind: missing
    claim: The frequency of policy exceptions is unknown.
    owner: Operations lead
    affects: [agency-necessity]
    resolved_by: Measure exception frequency over a representative month.
```

Describe the value gate before comparing technologies. Every outcome and constraint explicitly says whether it is binding, and every claim cites the evidence ledger. A binding outcome is ready for later assessment only when its baseline cites an observation or method-backed estimate.

```yaml
problem_value:
  outcomes:
    - id: reduce-handling-time
      description: Reduce routine-case handling time without lowering review quality.
      measure: Median handling minutes per completed case
      target: At most 8 minutes
      baseline_id: current-handling-time
      binding: true
      evidence_ids: [baseline-observation]
  baselines:
    - id: current-handling-time
      description: Current median handling time for representative routine cases.
      measure: Median handling minutes per completed case
      value: 12 minutes
      evidence_ids: [baseline-observation]
  constraints:
    - id: demand-capacity
      description: Compare each candidate against expected monthly demand.
      test: Supported completed cases per month
      required_result: Report for comparison; no minimum threshold
      binding: false
      evidence_ids: [volume-assumption]
  affected_volume:
    statement: The task handles a material monthly case volume.
    evidence_ids: [volume-assumption]
  material_pain:
    statement: Manual retrieval contributes avoidable handling effort.
    evidence_ids: [baseline-observation]
  error_cost:
    statement: Incorrect dispositions require rework before release.
    evidence_ids: [baseline-observation]
  technology_limitation:
    statement: Current search tooling may be contributing to handling time.
    evidence_ids: [volume-assumption]
```

Record agency facts separately from any agency conclusion. Readiness means the questions have credible evidence; it does not mean runtime model-directed control is necessary. Documents, many steps, legacy systems, exceptions, or an LLM are not substitutes for these facts.

```yaml
agency_necessity:
  execution_steps_predefinable:
    answer: "no"
    rationale: The next review step depends on the latest case evidence.
    evidence_ids: [workflow-estimate]
  step_count_or_order_predictable:
    answer: "no"
    rationale: The number and order of follow-up checks vary by case.
    evidence_ids: [workflow-estimate]
  runtime_tool_choice_required:
    answer: "yes"
    rationale: Different evidence gaps require different approved retrieval tools.
    evidence_ids: [workflow-estimate]
  runtime_replanning_required:
    answer: "yes"
    rationale: New evidence can invalidate the current review plan.
    evidence_ids: [workflow-estimate]
  environmental_feedback_available:
    answer: "yes"
    rationale: Each approved tool returns a typed success or failure result.
    evidence_ids: [workflow-estimate]
  completion_independently_verifiable:
    answer: "yes"
    rationale: Required checks and a draft disposition can be verified separately.
    evidence_ids: [workflow-estimate]
  effects_independently_verifiable:
    answer: "yes"
    rationale: No external release occurs inside the bounded task.
    evidence_ids: [workflow-estimate]
  fixed_workflow_sufficient:
    answer: "no"
    rationale: A fixed path cannot choose the next check for the residual case.
    evidence_ids: [workflow-estimate]
  residual_cases:
    - id: evidence-dependent-follow-up
      description: A submitted record introduces an unanticipated evidence gap.
      fixed_workflow_failure: The next approved retrieval step cannot be selected in advance.
      evidence_ids: [workflow-estimate]
```

Validate the dossier from this directory with:

```bash
archsift validate .
```

ArchSift treats dossier content as untrusted data. Do not place credentials in the dossier or commit confidential case material to a public repository.
