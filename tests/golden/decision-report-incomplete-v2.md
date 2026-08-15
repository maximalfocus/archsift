# ArchSift Decision Report

## Record Metadata

**Report Format Version**

    2

**Record Schema Version**

    2

**Record Content Identity**

    sha256:bf1c9811b516f0bdc94b1b0cdd8c456ca2f44ecb29c7eec111f0f21cfeb7228a

**Dossier Schema Version**

    1

**Case Language**

    en

**Dossier Content Identity**

    sha256:a97f558e41e5d0e86a28a59a96f81ca7c1071a6a972eb6d0f878ceface6a5260

**Ruleset Version**

    1.10.0

**Tool Version**

    0.1.0-test

**Assessment Configuration**

**Schema Version**

    1

**Entries**

    (none)

**Configuration Content Identity**

    sha256:b908f0089fe23bf8f8ec05339261d4bda95251fe99f96d3a9240cc985c48ec8c

## Case Identity

**Case**

**Id**

    incomplete

**Title**

    Synthetic incomplete

## Task Boundary

**Task**

    (not provided)

## Evidence Ledger

**Evidence**

    (none)

## Decision Areas

### Problem Value

**Problem Value**

    (not provided)

### Agency Necessity

**Agency Necessity**

    (not provided)

### Autonomy Permission

**Autonomy Permission**

    (not provided)

### Comparative Fit

**Candidate Comparison and Trade-offs**

    (not provided)

## Decision Conditions

**Decision Conditions**

    (none)

## Verdict and Recommendation

**Assessment Schema Version**

    1

**Assessment Ruleset Version**

    1.10.0

**Verdict**

    insufficient-evidence

**Verdict Rule ID**

    verdict-insufficient-evidence

**Qualitative Evidence State**

    evidence-incomplete

**Recommendation**

    (abstention)

**Surviving Candidate IDs**

    (none)

**Unmet Conditions**

    (none)

**Active Hard Veto IDs**

    (none)

**Mandatory Human Control IDs**

    (none)

## Assessment Trace

**Prerequisite Evaluation**

**Ruleset Version**

    1.10.0

**Ready**

    false

**Findings**

**Findings item 1**

**Rule Id**

    task-boundary-missing

**Field**

    $.task

**Requirement**

    FR-003

**Effect**

    require-evidence

**Message**

    The dossier does not define a bounded operational task.

**Consequence**

    Architecture assessment cannot proceed until this prerequisite is resolved.

**Remediation**

    Add the task boundary, actions, approval boundaries, and exclusions.

**Evidence Ids**

    (none)

**Counterpart**

    (not provided)

**Findings item 2**

**Rule Id**

    problem-value-missing

**Field**

    $.problem_value

**Requirement**

    FR-005

**Effect**

    require-evidence

**Message**

    The dossier does not define its problem-value contract.

**Consequence**

    Architecture assessment cannot proceed until this prerequisite is resolved.

**Remediation**

    Add measurable outcomes, baselines, constraints, and the four required statements.

**Evidence Ids**

    (none)

**Counterpart**

    (not provided)

**Findings item 3**

**Rule Id**

    agency-necessity-missing

**Field**

    $.agency_necessity

**Requirement**

    FR-006

**Effect**

    require-evidence

**Message**

    The dossier does not define its agency-necessity facts.

**Consequence**

    Architecture assessment cannot proceed until this prerequisite is resolved.

**Remediation**

    Answer all eight agency questions and record residual cases explicitly.

**Evidence Ids**

    (none)

**Counterpart**

    (not provided)

**Findings item 4**

**Rule Id**

    autonomy-permission-missing

**Field**

    $.autonomy_permission

**Requirement**

    FR-007

**Effect**

    require-evidence

**Message**

    The dossier does not define its autonomy-permission facts.

**Consequence**

    Architecture assessment cannot proceed until this prerequisite is resolved.

**Remediation**

    Answer all eight autonomy questions and record hard vetoes and human controls explicitly.

**Evidence Ids**

    (none)

**Counterpart**

    (not provided)

**Findings item 5**

**Rule Id**

    candidate-comparison-missing

**Field**

    $.candidate_comparison

**Requirement**

    FR-008

**Effect**

    require-evidence

**Message**

    The dossier does not define candidate-comparison facts.

**Consequence**

    Architecture assessment cannot proceed until this prerequisite is resolved.

**Remediation**

    Add candidates, roles, tests, and directional trade-off comparisons.

**Evidence Ids**

    (none)

**Counterpart**

    (not provided)

**Ordered Elimination Evaluation**

**Ruleset Version**

    1.10.0

**Candidates**

    (none)

**Control Classes**

    (none)

**Findings**

    (none)

**Least Surviving Class**

    (not provided)

## Evidence Identities

**Evidence Links**

    (none)

## Artefact Identities

**Artefact Links**

    (none)

## Unresolved Gaps

**Unresolved Gaps**

**Unresolved Gaps item 1**

**Source**

    prerequisite

**Rule Id**

    task-boundary-missing

**Field**

    $.task

**Requirement**

    FR-003

**Effect**

    require-evidence

**Message**

    The dossier does not define a bounded operational task.

**Consequence**

    Architecture assessment cannot proceed until this prerequisite is resolved.

**Remediation**

    Add the task boundary, actions, approval boundaries, and exclusions.

**Evidence Ids**

    (none)

**Counterpart**

    (not provided)

**Unresolved Gaps item 2**

**Source**

    prerequisite

**Rule Id**

    problem-value-missing

**Field**

    $.problem_value

**Requirement**

    FR-005

**Effect**

    require-evidence

**Message**

    The dossier does not define its problem-value contract.

**Consequence**

    Architecture assessment cannot proceed until this prerequisite is resolved.

**Remediation**

    Add measurable outcomes, baselines, constraints, and the four required statements.

**Evidence Ids**

    (none)

**Counterpart**

    (not provided)

**Unresolved Gaps item 3**

**Source**

    prerequisite

**Rule Id**

    agency-necessity-missing

**Field**

    $.agency_necessity

**Requirement**

    FR-006

**Effect**

    require-evidence

**Message**

    The dossier does not define its agency-necessity facts.

**Consequence**

    Architecture assessment cannot proceed until this prerequisite is resolved.

**Remediation**

    Answer all eight agency questions and record residual cases explicitly.

**Evidence Ids**

    (none)

**Counterpart**

    (not provided)

**Unresolved Gaps item 4**

**Source**

    prerequisite

**Rule Id**

    autonomy-permission-missing

**Field**

    $.autonomy_permission

**Requirement**

    FR-007

**Effect**

    require-evidence

**Message**

    The dossier does not define its autonomy-permission facts.

**Consequence**

    Architecture assessment cannot proceed until this prerequisite is resolved.

**Remediation**

    Answer all eight autonomy questions and record hard vetoes and human controls explicitly.

**Evidence Ids**

    (none)

**Counterpart**

    (not provided)

**Unresolved Gaps item 5**

**Source**

    prerequisite

**Rule Id**

    candidate-comparison-missing

**Field**

    $.candidate_comparison

**Requirement**

    FR-008

**Effect**

    require-evidence

**Message**

    The dossier does not define candidate-comparison facts.

**Consequence**

    Architecture assessment cannot proceed until this prerequisite is resolved.

**Remediation**

    Add candidates, roles, tests, and directional trade-off comparisons.

**Evidence Ids**

    (none)

**Counterpart**

    (not provided)

## Reassessment Triggers

**Reassessment Triggers**

    (none)

## Masking Notice

**Policy Version**

    1

**Warning**

    This record was emitted with deterministic sensitive-value masking (policy version 1). It is not guaranteed to be sensitive-data-free and still requires handling appropriate to its source material.
