# Contributing to ArchSift

Thank you for helping ArchSift make architecture decisions more evidence-driven and less technology-led.

## Issue-driven workflow

Every implementation change starts from one open, well-scoped GitHub issue whose body is the acceptance source.

1. Search existing issues before opening a new one.
2. Keep one issue independently reviewable; split epics before implementation.
3. Create a branch named `issue/<number>-<short-slug>`.
4. Keep the change limited to the issue and add tests at its acceptance boundary.
5. Open a focused pull request that links the issue and lists exact verification results.

Use `Closes #N` only when every acceptance item is proved. Otherwise use `Refs #N`.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Required checks

Run these after the final edit:

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m build
```

Do not commit generated build output, virtual environments, credentials, private case material, or proprietary policy text.

## Scope and conduct

ArchSift may reject a proposed feature when it adds complexity without reusable evidence. Case-derived changes should include a sanitised counterexample and regression test, never organisation-specific branching. All participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
