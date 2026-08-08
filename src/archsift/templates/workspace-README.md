# ArchSift case workspace

This directory contains one local architecture-decision case.

- `case.yaml` is the versioned, human-editable dossier.
- `evidence/` is reserved for local evidence artefacts; ledger provenance is inert metadata and validation does not open it.
- `output/` holds immutable content-addressed decision records; ArchSift never overwrites conflicting bytes.

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
    artefacts:
      - id: baseline-data
        root: workspace
        path: sanitised-baseline.csv
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
    artefacts:
      - id: representative-sample
        root: external
        path: trials/representative-sample.json
  - id: exception-gap
    kind: missing
    claim: The frequency of policy exceptions is unknown.
    owner: Operations lead
    affects: [agency-necessity]
    resolved_by: Measure exception frequency over a representative month.
  - id: autonomy-control-observation
    kind: observed
    claim: Consequential releases require recorded quality approval.
    owner: Risk reviewer
    affects: [autonomy-permission]
    provenance: evidence/sanitised-control-review.txt
    observed_at: 2026-08-07
```

`provenance` remains inert text naming the observation source; ArchSift never treats it as a path. An optional `artefacts` entry explicitly names bytes for later hashing. A `workspace` path is POSIX-relative to this workspace's `evidence/` directory. An `external` path is relative to an external evidence root that the caller must explicitly grant outside the dossier; the dossier cannot select that root itself. `archsift validate` checks only this authored reference contract and never opens either file.

After validation, produce an immutable JSON decision record and its Markdown review view with:

```console
archsift assess . --json
archsift assess . --external-evidence-root ../authorised-evidence --json
```

The external-root location is caller authority and is never stored in the record. Assessment writes the exact canonical JSON to `output/sha256-<record-id>.json` and a deterministic review view to the matching `.md` path. Both files carry the same record identity; identical reruns reuse byte-identical output without changing it, and a conflicting file is never overwritten. Authored values in Markdown are visibly quoted as inert data, so headings, links, HTML, controls, provenance, and artefact paths cannot become report structure or fetch instructions. `--json` still emits only canonical JSON to stdout. Custom output paths, comparison, and reassessment are not implemented yet.

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

Record autonomy facts separately from agency necessity and from any permission conclusion. Readiness means the facts and boundaries have credible evidence; it does not mean autonomy is permitted. Hard vetoes and mandatory human controls remain explicit and are never averaged into a score.

```yaml
autonomy_permission:
  actions_reversible:
    answer: "no"
    rationale: A released disposition cannot be withdrawn without a corrective process.
    evidence_ids: [autonomy-control-observation]
  failure_blast_radius_bounded:
    answer: "yes"
    rationale: Each disposition affects one submitted application.
    evidence_ids: [autonomy-control-observation]
  regulatory_automation_permitted:
    answer: "no"
    rationale: Consequential release requires an accountable human decision.
    evidence_ids: [autonomy-control-observation]
  data_confidence_sufficient:
    answer: "yes"
    rationale: Completeness is checked before the bounded review begins.
    evidence_ids: [autonomy-control-observation]
  accountable_owner_assigned:
    answer: "yes"
    rationale: The review operations lead remains accountable.
    evidence_ids: [autonomy-control-observation]
  decision_path_auditable:
    answer: "yes"
    rationale: The disposition, rationale, and approval are recorded.
    evidence_ids: [autonomy-control-observation]
  timely_human_intervention_available:
    answer: "yes"
    rationale: A quality approver can stop release before the external effect.
    evidence_ids: [autonomy-control-observation]
  safe_degradation_available:
    answer: "yes"
    rationale: The task can stop after drafting and queue human review.
    evidence_ids: [autonomy-control-observation]
  hard_vetoes:
    - id: no-autonomous-release
      status: active
      condition: A disposition would be released without quality approval.
      consequence: Autonomous release is prohibited.
      action_ids: [release-disposition]
      evidence_ids: [autonomy-control-observation]
  mandatory_human_controls:
    - id: approve-release
      description: Approve the disposition before external release.
      control_point: Immediately before release-disposition.
      responsible_role: Quality approver
      action_ids: [release-disposition]
      evidence_ids: [autonomy-control-observation]
```

Compare explicit candidates only after the problem, agency, and autonomy facts are recorded. Roles identify the current baseline, proposal, strongest simpler alternative, and (when present) one agentic comparator; they do not identify a winner. Candidates that inform the comparison without holding one of those decision-boundary roles use the required explicit form `roles: []`. Every named role still belongs to at most one candidate. Every result is directional from `subject_candidate_id` to `comparator_candidate_id`. `unknown` and assumptions remain visible but cannot make the comparison ready, and readiness is not a recommendation.

```yaml
candidate_comparison:
  candidates:
    - id: current-review
      name: Current human review
      description: Reviewers execute the bounded task using the current tools.
      control_class: human-owned-work
      roles: [current-baseline, strongest-simpler]
      material_deviations: []
      outcome_tests:
        - outcome_id: reduce-handling-time
          result: fails
          rationale: The current observed median exceeds the target.
          evidence_ids: [workflow-estimate]
      constraint_tests:
        - constraint_id: demand-capacity
          result: meets
          rationale: Current capacity is recorded for comparison without a minimum threshold.
          evidence_ids: [workflow-estimate]
    - id: fixed-review-workflow
      name: Fixed AI-assisted review workflow
      description: Code fixes the path while a model assists retrieval and drafting.
      control_class: fixed-ai-workflow
      roles: [proposed]
      material_deviations:
        - Consequential release remains outside the workflow.
      outcome_tests:
        - outcome_id: reduce-handling-time
          result: meets
          rationale: The representative-case estimate meets the target.
          evidence_ids: [workflow-estimate]
      constraint_tests:
        - constraint_id: demand-capacity
          result: meets
          rationale: Estimated capacity is recorded on the same case boundary.
          evidence_ids: [workflow-estimate]
  comparisons:
    - subject_candidate_id: fixed-review-workflow
      comparator_candidate_id: current-review
      dimensions:
        outcome_quality: &better
          result: better
          rationale: Representative cases show fewer retrieval omissions.
          evidence_ids: [workflow-estimate]
        difficult_case_performance: *better
        cost: &equivalent
          result: equivalent
          rationale: The current estimate does not establish a material difference.
          evidence_ids: [workflow-estimate]
        latency: *better
        human_effort: *better
        integration_burden: &worse
          result: worse
          rationale: The workflow adds maintained integrations.
          evidence_ids: [workflow-estimate]
        security_exposure: *worse
        failure_impact: *equivalent
        operability: *worse
        evaluation_burden: *worse
        maintainability: *worse
```

YAML anchors above only keep the sanitised example short; each expanded dimension is validated independently and must carry its own explicit result, rationale, and evidence IDs.

Use `decision_conditions` only for authored obligations that apply after the minimum-sufficient control class is already determined. A condition cannot eliminate or promote a class. If resolving an uncertainty could change the selected class, record it as missing evidence instead. Conditions remain separate from hard vetoes and mandatory human controls.

```yaml
decision_conditions:
  - id: verify-production-capacity
    target_control_class: fixed-ai-workflow
    decision_area: comparative-fit
    statement: Verify production capacity before adopting the fixed workflow.
    status: unmet
    resolved_by: Run the named production-capacity test and record whether its threshold passes.
    evidence_ids: [workflow-estimate]
```

Validate the dossier from this directory with:

```bash
archsift validate .
```

ArchSift treats dossier content as untrusted data. Do not place credentials in the dossier or commit confidential case material to a public repository.
