# ArchSift CLI exit codes

ArchSift commands use stable exit codes so scripts can distinguish invalid case data from tool failures.

| Code | Name | Meaning |
|---:|---|---|
| `0` | `SUCCESS` | The command completed successfully. |
| `2` | `USAGE` | Command-line arguments are invalid. |
| `10` | `MALFORMED_INPUT` | Input is not valid UTF-8 YAML/JSON or does not match the supported input contract. |
| `11` | `UNSUPPORTED_SCHEMA` | A dossier, decision record, usability result, or method-review result declares a version this ArchSift version does not support. |
| `12` | `VALIDATION_FAILED` | A workspace, dossier, usability cohort, or method-review result violates its supported contract or success criterion. |
| `13` | `UNSAFE_PATH` | A workspace, evidence, output, report, or comparison path cannot be resolved safely, stays outside its authorised root, or is not the required file/directory kind. |
| `14` | `ARTEFACT_UNAVAILABLE` | Assessment cannot read an explicitly referenced artefact, the caller did not grant its external evidence root, or a requested report, comparison, usability, or method-review record is unavailable. |
| `15` | `PERSISTENCE_FAILED` | A canonical JSON record, its Markdown review view, or a rendered report cannot be safely created or byte-identically reused, including an integrity conflict at any identity-derived path. |
| `70` | `INTERNAL_ERROR` | ArchSift failed internally rather than rejecting user input. |

A diagnostic identifies its file, field, governing requirement, and remediation. Validation errors retain their existing codes; a valid but incomplete dossier may still be assessed successfully as `insufficient-evidence`. Use `assess --json` for exact canonical decision-record bytes, `compare --json` for exact canonical comparison bytes, `usability-results --json` for a structured offline cohort result, and `method-review-results --json` for a structured offline architecture-method review result. Every command emits diagnostic JSON on failure with `--json`, or no output with `--quiet` when only the exit code is needed.
