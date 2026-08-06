# ArchSift case workspace

This directory contains one local architecture-decision case.

- `case.yaml` is the versioned, human-editable dossier.
- `evidence/` is reserved for evidence artefacts added in later workflow steps.
- `output/` is reserved for generated decision records and is safe to recreate.

Validate the dossier from this directory with:

```bash
archsift validate .
```

ArchSift treats dossier content as untrusted data. Do not place credentials in the dossier or commit confidential case material to a public repository.
