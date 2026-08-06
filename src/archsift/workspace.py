"""Case-workspace creation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import yaml

from archsift.diagnostics import Diagnostic, ExitCode


@dataclass(frozen=True, slots=True)
class InitResult:
    """Result of creating a case workspace."""

    exit_code: ExitCode
    workspace: Path
    diagnostics: tuple[Diagnostic, ...] = ()


_GENERATED_NAMES = ("case.yaml", "README.md", "evidence", "output")


def _case_id(name: str) -> str:
    identifier = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return identifier or "case"


def _write_text(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def initialize_workspace(target: Path) -> InitResult:
    """Create a deterministic version-1 case workspace without overwriting files."""
    display = str(target)
    if target.exists() and not target.is_dir():
        return InitResult(
            ExitCode.VALIDATION_FAILED,
            target,
            (
                Diagnostic(
                    id="workspace-target-not-directory",
                    message="The workspace target exists and is not a directory.",
                    file=display,
                    field="$",
                    requirement="FR-001",
                    remediation="Choose a missing or empty directory.",
                ),
            ),
        )

    if target.exists():
        entries = sorted(item.name for item in target.iterdir())
        if entries:
            return InitResult(
                ExitCode.VALIDATION_FAILED,
                target,
                (
                    Diagnostic(
                        id="workspace-not-empty",
                        message=f"The workspace target is not empty: {', '.join(entries)}.",
                        file=display,
                        field="$",
                        requirement="FR-001",
                        remediation=(
                            "Choose a missing or empty directory; ArchSift never overwrites it."
                        ),
                    ),
                ),
            )

    conflicts = [name for name in _GENERATED_NAMES if (target / name).exists()]
    if conflicts:
        return InitResult(
            ExitCode.VALIDATION_FAILED,
            target,
            (
                Diagnostic(
                    id="workspace-generated-path-exists",
                    message=f"Generated workspace paths already exist: {', '.join(conflicts)}.",
                    file=display,
                    field="$",
                    requirement="FR-001",
                    remediation=(
                        "Choose an empty directory; ArchSift never overwrites generated paths."
                    ),
                ),
            ),
        )

    target.mkdir(parents=True, exist_ok=True)
    dossier = {
        "schema_version": 1,
        "case": {"id": _case_id(target.name), "title": target.name or "Architecture decision"},
    }
    case_yaml = yaml.safe_dump(dossier, sort_keys=False, allow_unicode=True)
    guidance = (
        files("archsift").joinpath("templates/workspace-README.md").read_text(encoding="utf-8")
    )

    _write_text(target / "case.yaml", case_yaml)
    _write_text(target / "README.md", guidance)
    (target / "evidence").mkdir()
    (target / "output").mkdir()
    return InitResult(ExitCode.SUCCESS, target)
