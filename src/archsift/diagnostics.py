"""Stable diagnostics and process exit codes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
from unicodedata import category


class ExitCode(IntEnum):
    """Stable CLI process exit codes."""

    SUCCESS = 0
    USAGE = 2
    MALFORMED_INPUT = 10
    UNSUPPORTED_SCHEMA = 11
    VALIDATION_FAILED = 12
    UNSAFE_PATH = 13
    ARTEFACT_UNAVAILABLE = 14
    PERSISTENCE_FAILED = 15
    SUPERSEDED_BINDING = 16
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
        """Render a concise diagnostic without terminal control characters."""
        rendered = (
            f"{self.id} [{self.requirement}] {self.file}:{self.field}: {self.message} "
            f"Remediation: {self.remediation}"
        )
        return "".join(_escaped_control(character) for character in rendered)


def _escaped_control(character: str) -> str:
    """Escape C0/C1 and Unicode format controls while preserving visible text."""
    if category(character) not in {"Cc", "Cf"}:
        return character
    codepoint = ord(character)
    if codepoint <= 0xFF:
        return f"\\x{codepoint:02x}"
    if codepoint <= 0xFFFF:
        return f"\\u{codepoint:04x}"
    return f"\\U{codepoint:08x}"
