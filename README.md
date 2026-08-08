# ArchSift

**The minimum-sufficient architecture—or the evidence you still need.**

ArchSift is an open-source, local-first decision-support project for comparing human-owned work, process redesign, deterministic automation, fixed AI workflows, and runtime model-directed agency. It is designed to make evidence and trade-offs inspectable, and it may abstain when the available evidence cannot support a defensible decision.

> [!IMPORTANT]
> ArchSift is currently pre-alpha. The CLI can validate typed evidence, task, problem-value, agency-necessity, autonomy-permission, and candidate-comparison facts, inspect the packaged ruleset, and produce immutable content-addressed JSON decision records. The deterministic assessment core resolves minimum-sufficient architecture verdicts and binds canonical dossiers, explicit evidence-artefact bytes, ruleset, configuration, and tool version into each final record identity. Markdown decision reports, user-selected output paths, comparison, and reassessment are not implemented yet.

## Install for development

ArchSift requires a supported CPython version starting with Python 3.11.

```bash
git clone https://github.com/maximalfocus/archsift.git
cd archsift
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Current CLI

```bash
archsift --version
python -m archsift --version
archsift init my-case
archsift validate my-case
archsift validate my-case --json
archsift rules
archsift rules --json
archsift assess my-case
archsift assess my-case --json
archsift assess my-case --external-evidence-root ../authorised-evidence --json
```

`init` creates `case.yaml`, workspace guidance, and empty `evidence/` and `output/` directories. The dossier captures optional operational task, problem-value, agency-necessity, autonomy-permission, and candidate-comparison boundaries and distinguishes observations, assumptions, estimates, and known gaps without opening dossier-supplied paths. `validate` safely checks the versioned dossier, reports deterministic prerequisite readiness in JSON mode, and fails closed on malformed, unsupported, unknown, duplicate, or unsafe input. `rules` lists the immutable packaged rules without requiring a case workspace.

`assess` validates first, hashes only explicit workspace artefacts or external artefacts beneath the caller-granted `--external-evidence-root`, and writes canonical JSON to `output/sha256-<record-id>.json`. An identical rerun reuses byte-identical output without rewriting it; a non-identical file at that content address is never overwritten. `--json` emits those exact canonical bytes, while human and quiet modes never render dossier-authored text. See the [stable exit-code contract](docs/exit-codes.md).

No network service, model API, or telemetry is used by the current CLI.

## Development gate

```bash
python -m pytest
python -m benchmarks.large_dossier --max-seconds 2.0
python -m ruff check .
python -m ruff format --check .
python -m mypy src benchmarks tests/test_performance.py
python -m build
```

## Contributing and security

Development is issue-driven. Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a change. Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Licence

Apache License 2.0. See [LICENSE](LICENSE).
