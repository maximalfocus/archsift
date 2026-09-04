"""The standard evidence set: the profile every case is prepared into (FR-021)."""

from __future__ import annotations

import json
import re
from types import MappingProxyType
from typing import Any

import pytest

from archsift import vocabulary
from archsift.canonical import canonical_json_bytes
from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.evidence_set import (
    EVIDENCE_SET_PROFILE_SCHEMA_VERSION,
    evidence_bearing_locations,
    evidence_set_profile,
    profile_bytes,
    profile_lines,
    profile_payload,
    validate_slot_coverage,
)
from archsift.validation import (
    SUPPORTED_DOSSIER_SCHEMA_VERSIONS,
    DecisionArea,
    EvidenceKind,
    packaged_dossier_schema,
)
from archsift.vocabulary import (
    SLOTS,
    TASK_BOUNDARY_LOCATION,
    VocabularyError,
    excluded_words_in,
)


def _locations_by_independent_walk(schema_version: int) -> set[str]:
    """Enumerate evidence-bearing locations by a different traversal than the module's."""
    schema = packaged_dossier_schema(schema_version)
    definitions = schema["$defs"]
    bearing = {
        name
        for name, definition in definitions.items()
        if "evidence_ids" in definition.get("properties", {})
    }
    found: set[str] = set()
    stack: list[tuple[Any, str]] = [(schema, "$")]
    while stack:
        node, path = stack.pop()
        if not isinstance(node, dict):
            continue
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            if name in bearing:
                found.add(path)
            if not any(part == f"<{name}>" for part in path.split("/")):
                stack.append((definitions[name], path))
            continue
        for key, value in node.get("properties", {}).items():
            stack.append((value, f"{path}.{key}"))
        if "items" in node:
            stack.append((node["items"], f"{path}[]"))
        for keyword in ("anyOf", "oneOf", "allOf"):
            for alternative in node.get(keyword, []):
                stack.append((alternative, path))
    return found


@pytest.mark.parametrize("version", SUPPORTED_DOSSIER_SCHEMA_VERSIONS)
def test_profile_covers_exactly_the_evidence_bearing_locations_of_its_version(
    version: int,
) -> None:
    profile = evidence_set_profile(version)
    locations = [slot.location for slot in profile.slots]

    assert locations[0] == TASK_BOUNDARY_LOCATION
    assert set(locations[1:]) == _locations_by_independent_walk(version)
    assert set(locations[1:]) == set(evidence_bearing_locations(version))
    assert len(locations) == len(set(locations))
    assert ("$.candidate_comparison.baseline_retention" in locations) is (version >= 4)
    assert profile.dossier_schema_version == version
    assert profile.vocabulary_version == vocabulary.VOCABULARY_VERSION
    assert profile.framework_version == vocabulary.FRAMEWORK_VERSION


def test_profile_is_ordered_task_first_then_grouped_by_the_four_questions() -> None:
    profile = evidence_set_profile(5)

    assert profile.slots[0].question is None
    questions = [slot.question for slot in profile.slots[1:]]
    assert all(question is not None for question in questions)
    order = [area for area in DecisionArea]
    ranks = [order.index(question) for question in questions if question is not None]
    assert ranks == sorted(ranks)
    assert {question for question in questions} == set(DecisionArea)
    assert len(profile.slots) == 44
    # Within a question, the schema's own order: the four value statements follow
    # outcomes, baselines, and constraints exactly as the schema declares them.
    problem = [
        slot.location for slot in profile.slots if slot.question is DecisionArea.PROBLEM_VALUE
    ]
    assert problem[:3] == [
        "$.problem_value.outcomes[]",
        "$.problem_value.baselines[]",
        "$.problem_value.constraints[]",
    ]


def test_every_slot_carries_a_name_a_sentence_kinds_and_framework_rules() -> None:
    numbers = {rule.number for rule in vocabulary.FRAMEWORK_RULES}
    for location, slot in SLOTS.items():
        assert slot.name and slot.sentence.endswith("."), location
        assert slot.framework_rules and set(slot.framework_rules) <= numbers, location
        assert excluded_words_in(f"{slot.name} {slot.sentence}") == (), location
        assert "$." not in slot.name and "$." not in slot.sentence, location
        assert "_" not in slot.name and "_" not in slot.sentence, location
        if location == TASK_BOUNDARY_LOCATION:
            assert slot.kinds == ()
        else:
            assert slot.kinds and set(slot.kinds) <= set(EvidenceKind), location
    # Credible-support slots accept only an observation or an estimate.
    credible = {
        "$.problem_value.baselines[]",
        "$.agency_necessity.fixed_workflow_sufficient",
        "$.autonomy_permission.hard_vetoes[]",
        "$.candidate_comparison.candidates[].outcome_tests[]",
        "$.candidate_comparison.comparisons[].dimensions.cost",
        "$.candidate_comparison.strongest_simpler_boundary",
    }
    for location in credible:
        assert SLOTS[location].kinds == (EvidenceKind.OBSERVED, EvidenceKind.ESTIMATE), location
    assert set(SLOTS["$.problem_value.affected_volume"].kinds) == set(EvidenceKind)
    validate_slot_coverage()


def test_profile_fails_closed_on_an_unprofiled_location_and_an_orphan_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    without = {k: v for k, v in SLOTS.items() if k != "$.problem_value.error_cost"}
    monkeypatch.setattr(vocabulary, "SLOTS", MappingProxyType(without))
    with pytest.raises(VocabularyError, match=r"\$\.problem_value\.error_cost"):
        evidence_set_profile(5)

    orphan = {**SLOTS, "$.problem_value.invented[]": SLOTS["$.problem_value.outcomes[]"]}
    monkeypatch.setattr(vocabulary, "SLOTS", MappingProxyType(orphan))
    with pytest.raises(VocabularyError, match=r"invented"):
        validate_slot_coverage()

    with pytest.raises(VocabularyError, match="Unsupported"):
        evidence_set_profile(99)


def test_payload_is_deterministic_and_addressed_by_its_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = evidence_set_profile(5)
    payload = profile_payload(profile)

    assert profile_bytes(profile) == canonical_json_bytes(payload)
    assert profile_bytes(profile) == profile_bytes(evidence_set_profile(5))
    assert payload["evidence_set_profile_schema_version"] == EVIDENCE_SET_PROFILE_SCHEMA_VERSION
    assert set(payload) == {
        "dossier_schema_version",
        "evidence_set_profile_schema_version",
        "framework_version",
        "slots",
        "vocabulary_version",
    }
    first = payload["slots"][0]
    assert set(first) == {
        "acceptable_kinds",
        "framework_rules",
        "location",
        "name",
        "question",
        "sentence",
    }
    assert first["question"] is None and first["acceptable_kinds"] == []
    assert payload["slots"][1]["question"] == "problem-value"

    monkeypatch.setattr(vocabulary, "FRAMEWORK_VERSION", "9.9.9-test")
    assert profile_bytes(evidence_set_profile(5)) != profile_bytes(profile)
    assert evidence_set_profile(5).framework_version == "9.9.9-test"


def test_dossier_schema_emits_the_profile_only_when_asked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["dossier-schema", "--json"]) == ExitCode.SUCCESS
    plain = capsys.readouterr().out
    assert json.loads(plain)["$defs"]
    assert "evidence_set_profile_schema_version" not in plain

    assert main(["dossier-schema", "--evidence-set", "--json"]) == ExitCode.SUCCESS
    emitted = capsys.readouterr().out.encode("utf-8")
    assert emitted == profile_bytes(evidence_set_profile(5))

    assert main(["dossier-schema", "--schema-version", "1", "--evidence-set", "--json"]) == (
        ExitCode.SUCCESS
    )
    version_one = json.loads(capsys.readouterr().out)
    assert version_one["dossier_schema_version"] == 1
    assert len(version_one["slots"]) == 43

    assert main(["dossier-schema", "--evidence-set"]) == ExitCode.SUCCESS
    human = capsys.readouterr().out
    assert human.splitlines() == profile_lines(evidence_set_profile(5))
    assert human.startswith("Evidence set for case file format 5 (vocabulary ")
    for area in DecisionArea:
        assert f"\n{vocabulary.QUESTIONS[area]}\n" in human
    assert "$." not in human and "_" not in re.sub(r"\d", "", human)

    assert main(["dossier-schema", "--evidence-set", "--quiet"]) == ExitCode.SUCCESS
    assert capsys.readouterr().out == ""


def test_profile_never_touches_validation_or_assessment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Breaking the slot vocabulary breaks only the profile surface."""
    without = {k: v for k, v in SLOTS.items() if k != "$.problem_value.error_cost"}
    monkeypatch.setattr(vocabulary, "SLOTS", MappingProxyType(without))

    assert main(["dossier-schema", "--evidence-set"]) == ExitCode.INTERNAL_ERROR
    assert capsys.readouterr().err.startswith("internal-error [FR-012]")
    assert main(["dossier-schema", "--json"]) == ExitCode.SUCCESS
    assert json.loads(capsys.readouterr().out)["$defs"]
