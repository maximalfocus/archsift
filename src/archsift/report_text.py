"""Shared deterministic text-safety primitives for decision-record reports.

Every generated report representation renders the same authored strings. The
visibility transformation lives here so the Markdown review view (FR-011) and
the detailed HTML report (FR-016) cannot drift into two different escape
tables: identical authored input must reach a reader as identical visible text
in both representations, whatever the surrounding markup rules are.

Escaping that belongs to one markup language stays in that renderer.
"""

from __future__ import annotations

from typing import Final

# Fixed code-point ranges avoid Unicode-database drift across supported Python versions.
NON_PRINTING_RANGES: Final = (
    (0x0000, 0x001F),
    (0x007F, 0x009F),
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF9, 0xFFFB),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0001, 0xE0001),
    (0xE0020, 0xE007F),
    (0xE0100, 0xE01EF),
)


def visible_text(value: str) -> str:
    """Return ``value`` with every non-printing or bidirectional control made visible.

    Invisible characters cannot silently reorder, hide, or forge report text:
    each one becomes its own escape sequence, and a literal backslash is
    doubled so an escape sequence in the output is unambiguously generated.
    """
    rendered: list[str] = []
    for character in value:
        codepoint = ord(character)
        if character == "\\":
            rendered.append("\\\\")
        elif codepoint in {0x2028, 0x2029} or any(
            start <= codepoint <= end for start, end in NON_PRINTING_RANGES
        ):
            prefix, width = ("u", 4) if codepoint <= 0xFFFF else ("U", 8)
            rendered.append(f"\\{prefix}{codepoint:0{width}x}")
        else:
            rendered.append(character)
    return "".join(rendered)
