# Runnable synthetic examples

These fictional, domain-neutral workspaces demonstrate four distinct ArchSift decisions. They
contain no private data, require no network or model service, and use the same public CLI as any
other workspace.

| Workspace | Expected verdict | Expected class | Evidence state |
| --- | --- | --- | --- |
| [No technology change](no-technology-change/) | `no-technology-change` | `human-owned-work` | `evidence-complete` |
| [Fixed workflow](fixed-workflow/) | `supported` | `fixed-ai-workflow` | `evidence-complete` |
| [Agentic control](agentic-control/) | `supported` | `agentic-control` | `evidence-complete` |
| [Insufficient evidence](insufficient-evidence/) | `insufficient-evidence` | none | `evidence-incomplete` |

From the repository root, validate or assess any workspace:

```bash
python -m archsift validate examples/no-technology-change --json
python -m archsift assess examples/no-technology-change --json
```

Assessment writes an immutable JSON record and Markdown review view beneath that workspace's
`output/` directory. Generated records are intentionally ignored; the maintained sources are
`case.yaml`, `evidence/`, the workspace README, and an empty `output/.gitkeep`. The
machine-readable [manifest](manifest.json) is the test and CI contract for every example.

The independently authored synthetic
[`graph-corpus-request.json`](graph-corpus-request.json) demonstrates an
explicit reusable rationale-to-rule trace and visible competing knowledge using
the packaged corpus while preserving the fixed-workflow assessment and verdict:

```bash
archsift graph-corpus --json > architecture-v1.json
archsift graph-view architecture-v1.json examples/graph-corpus-request.json --json
archsift assess examples/fixed-workflow --graph-snapshot architecture-v1.json --graph-request examples/graph-corpus-request.json --json
```
