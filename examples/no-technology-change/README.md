# No technology change

This fictional case shows a current human procedure that misses the binding quality outcome and a
reorganised intake, still human executed, that meets it. The expected result is
`no-technology-change`, class `process-redesign`, with `evidence-complete`. In the trace,
`binding-outcome-met` cites `decision-observed` for the redesigned intake, and `binding-outcome-failed`
cites it for the current procedure. Because the current baseline credibly fails a binding outcome, the
binding set discriminates between the candidates and the `non-discriminating-binding-set` prerequisite
does not apply.

From the repository root:

```bash
python -m archsift validate examples/no-technology-change --json
python -m archsift assess examples/no-technology-change --json
```

Inspect the findings below `assessment` for `rule_id` and `evidence_ids`; the assessment's active
veto and mandatory-control IDs show constraints, while `unresolved_gaps` shows missing evidence.
Generated JSON and Markdown records appear in `examples/no-technology-change/output/` and are not
source files.
