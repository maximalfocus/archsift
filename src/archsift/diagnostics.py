"""Stable diagnostics and process exit codes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum


class ExitCode(IntEnum):
    """Stable CLI process exit codes."""

    SUCCESS = 0
    USAGE = 2
    MALFORMED_INPUT = 10
    UNSUPPORTED_SCHEMA = 11
    VALIDATION_FAILED = 12
    UNSAFE_PATH = 13
    INTERNAL_ERROR = 70


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One actionable validation or workspace diagnostic."""

    id: str
    message: str
    file: str
    field: str
    requirement: str
    remediation: str

    def to_dict(self) -> dict[str, str]:
        """Return a deterministic JSON-compatible representation."""
        return asdict(self)

    def render(self) -> str:
        """Render a concise human-readable diagnostic."""
        return (
            f"{self.id} [{self.requirement}] {self.file}:{self.field}: {self.message} "
            f"Remediation: {self.remediation}"
        )
