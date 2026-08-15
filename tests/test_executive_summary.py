from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from archsift.canonical import JsonObject, JsonValue
from archsift.executive_summary import (
    DERIVED_MARKERS,
    ExecutiveSummary,
    build_executive_summary,
    is_derived_value,
)
from archsift.masking import masked_decision_record_view
from archsift.record_view import ReportRecordError

_GOLDEN_DIR = Path(__file__).parent / "golden"
_POSITIVE_RECORD = _GOLDEN_DIR / "decision-record-positive-v1.json"
_INCOMPLETE_RECORD = _GOLDEN_DIR / "decision-record-incomplete-v1.json"
_ABSTENTION_RECORD = _GOLDEN_DIR / "decision-record-abstention-veto-v1.json"

_ALL_RECORDS = (_POSITIVE_RECORD, _INCOMPLETE_RECORD, _ABSTENTION_RECORD)


def _record(path: Path = _POSITIVE_RECORD) -> JsonObject:
    return cast(JsonObject, json.loads(path.read_bytes()))


def _record_strings(record: JsonObject) -> set[str]:
    """Return every string the record itself contains, at any depth."""
    found: set[str] = set()

    def walk(value: JsonValue) -> None:
        if type(value) is list:
            for item in cast(list[JsonValue], value):
                walk(item)
        elif type(value) is dict:
            mapping = cast(JsonObject, value)
            for key in sorted(mapping):
                found.add(key)
                walk(mapping[key])
        elif type(value) is str:
            found.add(value)

    walk(cast(JsonValue, record))
    return found


def _labels(summary: ExecutiveSummary) -> list[str]:
    return [point.label for section in summary.sections for point in section.points]


@pytest.mark.parametrize("path", _ALL_RECORDS, ids=lambda path: path.stem)
def test_summary_introduces_no_fact_absent_from_the_record(path: Path) -> None:
    """FR-017: the summary states nothing the record does not contain."""
    record = _record(path)
    summary = build_executive_summary(record)
    available = _record_strings(masked_decision_record_view(record))

    quoted = 0
    for section in summary.sections:
        for point in section.points:
            assert point.values, point.label
            for value in point.values:
                if point.derived:
                    assert is_derived_value(value), (point.label, value)
                    continue
                assert value in available, (point.label, value)
                quoted += 1
    assert quoted >= 4


@pytest.mark.parametrize("path", _ALL_RECORDS, ids=lambda path: path.stem)
def test_summary_covers_every_required_element(path: Path) -> None:
    summary = build_executive_summary(_record(path))

    assert [section.title for section in summary.sections] == [
        "Case and Task Boundary",
        "Verdict",
        "Decision Space",
        "Vetoes and Mandatory Human Controls",
        "Evidence State",
        "Decisive Trade-offs",
    ]
    labels = _labels(summary)
    for required in (
        "Case ID",
        "Case",
        "Verdict",
        "Verdict Rule",
        "Recommendation",
        "Evidence State",
        "Observed",
        "Assumption",
        "Estimate",
        "Missing",
    ):
        assert required in labels, required
    assert summary.record_content_identity == _record(path)["record_content_identity"]
    assert summary.ruleset_version == _record(path)["ruleset_version"]
    assert summary.tool_version == _record(path)["tool_version"]


def test_summary_states_an_abstention_together_with_its_active_veto() -> None:
    """The acceptance record: an abstaining verdict that still carries a veto."""
    summary = build_executive_summary(_record(_ABSTENTION_RECORD))
    points = {point.label: point for section in summary.sections for point in section.points}

    assert points["Verdict"].values == ("insufficient-evidence",)
    assert points["Recommendation"].values == ("(abstention)",)
    assert points["Recommendation"].derived is True
    assert points["Active Veto"].values[0] == "human-release-required"
    assert points["Mandatory Human Control"].values[0] == "approve-release"
    assert points["Missing"].derived is True


def test_summary_reports_a_no_permissible_candidate_outcome() -> None:
    record = _record()
    assessment = cast(dict[str, Any], record["assessment"])
    assessment["recommended_class"] = None
    assessment["verdict"] = "no-permissible-candidate"

    summary = build_executive_summary(record)

    recommendation = next(
        point
        for section in summary.sections
        for point in section.points
        if point.label == "Recommendation"
    )
    assert recommendation.values == ("(no permissible candidate)",)
    assert recommendation.derived is True
    assert set(recommendation.values) <= DERIVED_MARKERS


def test_trade_offs_select_only_directional_outcomes_touching_the_deciding_candidates() -> None:
    record = _record()
    comparison = cast(dict[str, Any], record["dossier"])["candidate_comparison"]
    # `fixed` is the sole surviving candidate; `human`/`deterministic` is not.
    assert cast(dict[str, Any], record["assessment"])["surviving_candidate_ids"] == ["fixed"]
    deciding = next(
        pair for pair in comparison["comparisons"] if pair["subject_candidate_id"] == "fixed"
    )
    other = next(
        pair
        for pair in comparison["comparisons"]
        if "fixed" not in (pair["subject_candidate_id"], pair["comparator_candidate_id"])
    )
    deciding["dimensions"]["cost"]["result"] = "worse"
    deciding["dimensions"]["latency"]["result"] = "better"
    deciding["dimensions"]["operability"]["result"] = "unknown"
    other["dimensions"]["cost"]["result"] = "better"

    summary = build_executive_summary(record)
    trade_offs = next(
        section for section in summary.sections if section.title == "Decisive Trade-offs"
    )

    # Declared FR-008 dimension order (cost before latency), not mapping order.
    assert [point.label for point in trade_offs.points] == [
        "Trade-off (Cost)",
        "Trade-off (Latency)",
    ]
    for point in trade_offs.points:
        assert point.values[0] == "fixed" or point.values[1] == "fixed"
        assert point.values[2] in {"better", "worse"}
    assert all("Operability" not in point.label for point in trade_offs.points)


def test_trade_offs_fall_back_to_the_proposed_candidate_when_none_survives() -> None:
    record = _record()
    assessment = cast(dict[str, Any], record["assessment"])
    assessment["surviving_candidate_ids"] = []
    assessment["recommended_class"] = None
    assessment["verdict"] = "insufficient-evidence"
    comparison = cast(dict[str, Any], record["dossier"])["candidate_comparison"]
    proposed = next(
        pair for pair in comparison["comparisons"] if pair["subject_candidate_id"] == "fixed"
    )
    proposed["dimensions"]["cost"]["result"] = "worse"

    summary = build_executive_summary(record)
    trade_offs = next(
        section for section in summary.sections if section.title == "Decisive Trade-offs"
    )

    assert [point.label for point in trade_offs.points] == ["Trade-off (Cost)"]


def test_a_record_without_directional_outcomes_states_that_plainly() -> None:
    summary = build_executive_summary(_record())
    trade_offs = next(
        section for section in summary.sections if section.title == "Decisive Trade-offs"
    )

    assert [point.label for point in trade_offs.points] == ["Directional Trade-offs"]
    assert trade_offs.points[0].values == ("(none)",)
    assert trade_offs.points[0].derived is True


def test_absent_dossier_sections_are_marked_rather_than_invented() -> None:
    summary = build_executive_summary(_record(_INCOMPLETE_RECORD))
    points = [point for section in summary.sections for point in section.points]
    by_label = {point.label: point for point in points}

    for label in ("Task Boundary", "Candidates", "Autonomy Boundary", "Trade-offs"):
        assert by_label[label].values == ("(not provided)",), label
        assert by_label[label].derived is True, label
    gaps = [point.values[0] for point in points if point.label == "Unresolved Gap"]
    assert "task-boundary-missing" in gaps


def test_evidence_counts_and_material_gaps_come_from_the_ledger() -> None:
    summary = build_executive_summary(_record(_INCOMPLETE_RECORD))
    section = next(item for item in summary.sections if item.title == "Evidence State")
    counts = {point.label: point.values[0] for point in section.points if point.derived}

    assert counts["Observed"] == "0"
    assert counts["Assumption"] == "1"
    assert counts["Estimate"] == "0"
    assert counts["Missing"] == "1"
    gaps = [point for point in section.points if point.label == "Unresolved Gap"]
    assert len(gaps) == 5
    material = [point for point in section.points if point.label == "Material Gap"]
    assert len(material) == 1 and material[0].values[0] == "a-missing"


def test_summary_masks_authored_values_and_is_idempotent() -> None:
    record = _record()
    dossier = cast(dict[str, Any], record["dossier"])
    dossier["case"]["title"] = "Card 4111 1111 1111 1111 and api_key: AKIAIOSFODNN7EXAMPLE"
    record.pop("masking", None)

    summary = build_executive_summary(record)

    assert "4111 1111 1111 1111" not in summary.case_title
    assert "AKIAIOSFODNN7EXAMPLE" not in summary.case_title
    assert "[ARCHSIFT-MASKED:payment-card]" in summary.case_title
    assert "[ARCHSIFT-MASKED:credential]" in summary.case_title
    assert build_executive_summary(masked_decision_record_view(record)) == summary


def test_building_is_pure_and_repeatable() -> None:
    record = _record()
    before = json.dumps(record, sort_keys=True)

    first = build_executive_summary(record)
    second = build_executive_summary(record)

    assert first == second
    assert json.dumps(record, sort_keys=True) == before


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda record: record.pop("assessment"), r"\$ is missing assessment"),
        (
            lambda record: cast(dict[str, Any], record["dossier"]).__setitem__("evidence", {}),
            r"\$\.dossier\.evidence is not a JSON array",
        ),
        (
            lambda record: cast(dict[str, Any], record["dossier"])["evidence"][0].__setitem__(
                "kind", "rumour"
            ),
            r"evidence kind rumour is unsupported",
        ),
        (
            lambda record: cast(dict[str, Any], record["dossier"])["case"].__setitem__("title", 7),
            r"\$\.dossier\.case\.title is not text",
        ),
    ],
)
def test_unsupported_record_shape_fails_closed(mutate: Any, match: str) -> None:
    record = _record()
    mutate(record)

    with pytest.raises(ReportRecordError, match=match):
        build_executive_summary(record)


def test_derived_value_vocabulary_is_closed() -> None:
    assert is_derived_value("0") and is_derived_value("12") and is_derived_value("1 of 3")
    for marker in DERIVED_MARKERS:
        assert is_derived_value(marker), marker
    for quoted in ("fixed-ai-workflow", "1 of", "of 3", "", "none", "(unknown)"):
        assert not is_derived_value(quoted), quoted
