# ArchSift case workspace

This directory contains one local architecture-decision case.

- `case.yaml` is the versioned, human-editable dossier.
- `evidence/` is reserved for local evidence artefacts; ledger provenance is inert metadata and validation does not open it.
- `output/` is reserved for generated decision records and is safe to recreate.

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

Validate the dossier from this directory with:

```bash
archsift validate .
```

ArchSift treats dossier content as untrusted data. Do not place credentials in the dossier or commit confidential case material to a public repository.
