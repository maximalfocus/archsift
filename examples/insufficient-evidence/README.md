# Insufficient evidence

This fictional case is structurally complete but intentionally records an unknown fixed-workflow
outcome and comparison result. It demonstrates abstention without malformed input. The expected
result is `insufficient-evidence`, no recommended class, with `evidence-incomplete`. In the trace,
`comparison-result-unknown` cites `decision-observed`.

From the repository root:

```bash
python -m archsift validate examples/insufficient-evidence --json
python -m archsift assess examples/insufficient-evidence --json
```

Inspect the findings below `assessment` for `rule_id` and `evidence_ids`; the assessment's active
veto and mandatory-control IDs show constraints, while `unresolved_gaps` names what evidence must
be resolved. Generated JSON and Markdown records appear in
`examples/insufficient-evidence/output/` and are not source files.
