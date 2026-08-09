# No technology change

This fictional case shows that the human-owned process already meets the binding outcome and
constraint. The expected result is `no-technology-change`, class `human-owned-work`, with
`evidence-complete`. In the trace, `binding-outcome-met` cites `decision-observed`.

From the repository root:

```bash
python -m archsift validate examples/no-technology-change --json
python -m archsift assess examples/no-technology-change --json
```

Inspect the findings below `assessment` for `rule_id` and `evidence_ids`; the assessment's active
veto and mandatory-control IDs show constraints, while `unresolved_gaps` shows missing evidence.
Generated JSON and Markdown records appear in `examples/no-technology-change/output/` and are not
source files.
