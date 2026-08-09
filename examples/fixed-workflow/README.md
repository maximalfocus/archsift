# Fixed AI workflow

This fictional case shows the current human process missing the binding outcome while a fixed AI
workflow meets it. Runtime model-directed adaptation is unnecessary. The expected result is
`supported`, class `fixed-ai-workflow`, with `evidence-complete`. In the trace,
`binding-outcome-met` cites `decision-observed` for the fixed candidate.

From the repository root:

```bash
python -m archsift validate examples/fixed-workflow --json
python -m archsift assess examples/fixed-workflow --json
```

Inspect the findings below `assessment` for `rule_id` and `evidence_ids`; the assessment's active
veto and mandatory-control IDs show constraints, while `unresolved_gaps` shows missing evidence.
Generated JSON and Markdown records appear in `examples/fixed-workflow/output/` and are not source
files.
