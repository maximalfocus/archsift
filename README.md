# ArchSift

**The minimum-sufficient architecture—or the evidence you still need.**

ArchSift is an open-source, local-first decision-support project for comparing human-owned work, process redesign, deterministic automation, fixed AI workflows, and runtime model-directed agency. It is designed to make evidence and trade-offs inspectable, and it may abstain when the available evidence cannot support a defensible decision.

> [!IMPORTANT]
> ArchSift is currently pre-alpha. The CLI can validate a versioned case workspace with a typed evidence ledger and operational task boundary; problem-value analysis and the assessment engine are not implemented yet.

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
```

`init` creates `case.yaml`, workspace guidance, and empty `evidence/` and `output/` directories. The dossier captures an optional operational task boundary and distinguishes observations, assumptions, estimates, and known gaps without opening task or provenance metadata. `validate` safely checks the versioned dossier and fails closed on malformed, unsupported, unknown, duplicate, or unsafe input. See the [stable exit-code contract](docs/exit-codes.md).

No network service, model API, or telemetry is used by the current CLI.

## Development gate

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m build
```

## Contributing and security

Development is issue-driven. Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a change. Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Licence

Apache License 2.0. See [LICENSE](LICENSE).
