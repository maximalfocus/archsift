# ArchSift CLI exit codes

ArchSift commands use stable exit codes so scripts can distinguish invalid case data from tool failures.

| Code | Name | Meaning |
|---:|---|---|
| `0` | `SUCCESS` | The command completed successfully. |
| `2` | `USAGE` | Command-line arguments are invalid. |
| `10` | `MALFORMED_INPUT` | Input is not readable UTF-8 YAML or is not a YAML mapping. |
| `11` | `UNSUPPORTED_SCHEMA` | The dossier declares a schema version this ArchSift version does not support. |
| `12` | `VALIDATION_FAILED` | The workspace or dossier violates the supported structural contract. |
| `13` | `UNSAFE_PATH` | A workspace, evidence, or output path cannot be resolved safely, stays outside its authorised root, or is not the required file/directory kind. |
| `14` | `ARTEFACT_UNAVAILABLE` | Assessment cannot read an explicitly referenced artefact or the caller did not grant its external evidence root. |
| `15` | `PERSISTENCE_FAILED` | A canonical record cannot be safely created or byte-identically reused, including an integrity conflict at its content address. |
| `70` | `INTERNAL_ERROR` | ArchSift failed internally rather than rejecting user input. |

A diagnostic identifies its file, field, governing requirement, and remediation. Validation errors retain their existing codes; a valid but incomplete dossier may still be assessed successfully as `insufficient-evidence`. Use `assess --json` for exact canonical decision-record bytes on success, diagnostic JSON on failure, or `--quiet` when only the exit code is needed.
