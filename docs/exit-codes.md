# ArchSift CLI exit codes

ArchSift commands use stable exit codes so scripts can distinguish invalid case data from tool failures.

| Code | Name | Meaning |
|---:|---|---|
| `0` | `SUCCESS` | The command completed successfully. |
| `2` | `USAGE` | Command-line arguments are invalid. |
| `10` | `MALFORMED_INPUT` | Input is not readable UTF-8 YAML or is not a YAML mapping. |
| `11` | `UNSUPPORTED_SCHEMA` | The dossier declares a schema version this ArchSift version does not support. |
| `12` | `VALIDATION_FAILED` | The workspace or dossier violates the supported structural contract. |
| `13` | `UNSAFE_PATH` | A workspace path cannot be resolved safely: it escapes the workspace boundary or cannot be resolved (symlink loop, permission failure). |
| `70` | `INTERNAL_ERROR` | ArchSift failed internally rather than rejecting user input. |

A validation diagnostic identifies its file, field, governing requirement, and remediation. Use `--json` for deterministic machine-readable output or `--quiet` when only the exit code is needed.
