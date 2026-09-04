"""The evidence-set profile as the authoring target in the guidance and the protocol (FR-021)."""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

import pytest

from archsift import vocabulary
from archsift.authoring_results import (
    PROTOCOL_VERSION,
    PROTOCOL_VERSION_1_0_0,
    PROTOCOL_VERSION_1_0_1,
    SUPPORTED_PROTOCOL_VERSIONS,
)
from archsift.decision import ArchitectureVerdict
from archsift.diagnostics import ExitCode
from archsift.evidence_set import evidence_set_profile, guidance_lines
from archsift.language import EVIDENCE_SET_MARKER, workspace_guidance
from archsift.rules import list_rules
from archsift.validation import ControlClass
from archsift.vocabulary import excluded_words_in
from archsift.workspace import initialize_workspace

ROOT = Path(__file__).resolve().parents[1]


def _narrative(guidance: str) -> str:
    """Return the guidance prose without its fenced code blocks."""
    return re.sub(r"```.*?```", "", guidance, flags=re.S)


def test_init_writes_the_profile_as_the_authoring_target_in_profile_order(tmp_path: Path) -> None:
    target = tmp_path / "case"
    assert initialize_workspace(target).exit_code is ExitCode.SUCCESS
    guidance = (target / "README.md").read_text(encoding="utf-8")
    profile = evidence_set_profile(1)

    assert guidance == workspace_guidance("en")
    assert EVIDENCE_SET_MARKER not in guidance
    section = guidance.split("## The evidence set", 1)[1].split("## Recording the case", 1)[0]
    assert "reduce interviews, documents, measurements, and source repositories" in section.lower()
    assert "recorded context" in section
    positions = []
    for slot in profile.slots:
        marker = f"- **{slot.phrases.name}.** {slot.phrases.sentence}"
        assert marker in section, slot.location
        positions.append(section.index(marker))
        for kind in slot.kind_phrases:
            assert kind in section
    assert positions == sorted(positions)
    assert len(re.findall(r"^- \*\*", section, flags=re.M)) == len(profile.slots) == 43
    for area, question in vocabulary.QUESTIONS.items():
        assert f"**{question}**" in section, area
    # The profile of the workspace's schema version: schema 1 has no kept-baseline slot.
    assert "Keeping the current way of working" not in section
    assert "\n".join(guidance_lines(profile)) in section


def test_guidance_narrative_stays_in_the_register(tmp_path: Path) -> None:
    prose = _narrative(workspace_guidance("en"))
    section = prose.split("## The evidence set", 1)[1].split("## Recording the case", 1)[0]

    assert excluded_words_in(section) == ()
    assert "$." not in section
    for rule in list_rules():
        assert rule.id not in section
    assert re.search(r"\bN?FR-\d{3}\b", section) is None
    for token in (
        *(verdict.value for verdict in ArchitectureVerdict),
        *(control_class.value for control_class in ControlClass),
        "require-evidence",
        "support-candidate",
    ):
        assert re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", section) is None, token


def test_guidance_is_deterministic_and_the_examples_keep_their_positions(tmp_path: Path) -> None:
    first = initialize_workspace(tmp_path / "one")
    second = initialize_workspace(tmp_path / "two")
    assert first.exit_code is second.exit_code is ExitCode.SUCCESS
    assert (tmp_path / "one" / "README.md").read_bytes() == (
        tmp_path / "two" / "README.md"
    ).read_bytes()
    template = files("archsift").joinpath("templates/workspace-README.md").read_text("utf-8")
    assert EVIDENCE_SET_MARKER in template
    # The worked examples other tests index by position are untouched.
    assert template.count("```yaml") == workspace_guidance("en").count("```yaml") >= 5
    assert workspace_guidance("en", schema_version=5).count("- **") == 44


def test_protocol_1_1_0_fills_the_profile_and_earlier_protocols_stay_frozen() -> None:
    current = (ROOT / "docs/authoring-check-v1.1.0.md").read_text(encoding="utf-8")
    words = " ".join(current.split())

    assert PROTOCOL_VERSION == "1.1.0"
    assert SUPPORTED_PROTOCOL_VERSIONS == (
        PROTOCOL_VERSION_1_0_0,
        PROTOCOL_VERSION_1_0_1,
        PROTOCOL_VERSION,
    )
    assert "protocol 1.1.0" in words
    assert "archsift dossier-schema --schema-version 3 --evidence-set --json" in current
    assert "by filling the profile's slots" in words
    assert "explicitly missing or unknown" in words
    assert "No cohort has been run under protocol 1.1.0" in words
    # Frozen contract unchanged.
    assert "exactly four fresh sessions" in words
    assert "four distinct agent products" in words
    assert "at least three of the four sessions" in words
    for milestone in (
        "register_material",
        "inspect_schema",
        "author_dossier",
        "complete_prerequisites",
        "validate",
        "assess",
    ):
        assert f"`{milestone}`" in current, milestone
    earlier = (ROOT / "docs/authoring-check-v1.0.1.md").read_text(encoding="utf-8")
    assert "--evidence-set" not in earlier
    assert "protocol 1.0.1" in " ".join(earlier.split())
    packaging = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for name in ("authoring-check-v1.md", "authoring-check-v1.0.1.md", "authoring-check-v1.1.0.md"):
        assert f'"docs/{name}" = "archsift/docs/{name}"' in packaging, name


@pytest.mark.parametrize("version", [PROTOCOL_VERSION_1_0_0, PROTOCOL_VERSION_1_0_1])
def test_results_bound_to_an_earlier_protocol_still_validate(version: str) -> None:
    from archsift.authoring_results import validate_authoring_results

    committed = ROOT / "authoring-results.json"
    result = validate_authoring_results(committed)
    assert result.exit_code is ExitCode.SUCCESS
    assert result.protocol_version == PROTOCOL_VERSION_1_0_1
    assert version in SUPPORTED_PROTOCOL_VERSIONS
