# ArchSift CLI exit codes

ArchSift commands use stable exit codes so scripts can distinguish invalid case data from tool failures.

| Code | Name | Meaning |
|---:|---|---|
| `0` | `SUCCESS` | The command completed successfully. |
| `2` | `USAGE` | Command-line arguments are invalid. |
| `10` | `MALFORMED_INPUT` | Input is not valid UTF-8 YAML/JSON or does not match the supported input contract. |
| `11` | `UNSUPPORTED_SCHEMA` | A dossier, decision record, graph snapshot, graph-change proposal, graph-view request, usability result, authoring result, or method-review result declares a version this ArchSift version does not support. |
| `12` | `VALIDATION_FAILED` | A workspace, dossier, declared case language, material registration, graph snapshot, graph-change proposal, graph-view request or assessment binding, usability cohort, authoring cohort, or method-review result violates its supported contract or success criterion. |
| `13` | `UNSAFE_PATH` | A workspace, material-registration source, evidence, output, report, comparison, graph-snapshot, graph-change, graph-assessment, or cohort-result input path cannot be resolved safely, stays outside its authorised root, or is not the required file/directory kind. |
| `14` | `ARTEFACT_UNAVAILABLE` | Assessment or registration cannot read an explicitly referenced regular file, the caller did not grant its external root, or a requested report, comparison, graph snapshot/change/view input, usability, authoring, or method-review record is unavailable. |
| `15` | `PERSISTENCE_FAILED` | A material registration, canonical JSON record, its Markdown review view, or a rendered report cannot be safely created or byte-identically reused, including an integrity conflict at any identity-derived path. |
| `16` | `SUPERSEDED_BINDING` | A method-review result is valid historical evidence for an explicitly registered superseded method, ruleset, and example-corpus binding. Its status still states whether that cohort met its criterion; it is not current-binding evidence. |
| `70` | `INTERNAL_ERROR` | ArchSift failed internally rather than rejecting user input. |

A diagnostic identifies its file, field, governing requirement, and remediation. Validation errors retain their existing codes; a valid but incomplete dossier may still be assessed successfully as `insufficient-evidence`. Use `dossier-schema --json` for a complete packaged authoring contract, `prerequisites --json` for a versioned decision-completeness worklist, `register-document --json` or `register-repository --json` for a structured immutable-registration summary, `assess --json` for exact canonical decision-record bytes, `compare --json` for exact canonical comparison bytes, `graph-corpus --json` for the exact packaged snapshot bytes, `graph-snapshot --json` for a validated snapshot identity and typed inventory, `graph-change --json` for a validated evolution summary, `graph-view --json` for a deterministic private case view, `usability-results --json` or `authoring-results --json` for structured offline cohort results, and `method-review-results --json` for a structured offline architecture-method review result. Every command emits diagnostic JSON on failure with `--json`, or no output with `--quiet` when only the exit code is needed.
