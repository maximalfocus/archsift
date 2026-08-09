# Agentic control

This fictional case makes the agency boundary explicit: the human and fixed candidates miss the
binding outcome; a fixed workflow is insufficient; an evidence-dependent residual remains; runtime
tool choice, environmental feedback, and permitted bounded authority support the agentic candidate.
The expected result is `supported`, class `agentic-control`, with `evidence-complete`. In the trace,
`agentic-runtime-adaptation-supports-agency` cites `agency-observed`.

From the repository root:

```bash
python -m archsift validate examples/agentic-control --json
python -m archsift assess examples/agentic-control --json
```

Inspect the findings below `assessment` for `rule_id` and `evidence_ids`; the assessment's active
veto and mandatory-control IDs show constraints, while `unresolved_gaps` shows missing evidence.
Generated JSON and Markdown records appear in `examples/agentic-control/output/` and are not source
files.
