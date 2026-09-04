"""The three-part executive summary model (FR-017, NFR-011)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest

from archsift.canonical import JsonObject, JsonValue
from archsift.executive_summary import (
    PART_TITLES,
    ExecutiveSummary,
    build_executive_summary,
)
from archsift.masking import masked_decision_record_view
from archsift.record_view import ReportRecordError
from archsift.vocabulary import (
    DECISION_OWNER_STATEMENT,
    FLAG_MEANINGS,
    VOCABULARY_VERSION,
    excluded_words_in,
)

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


def _statements(summary: ExecutiveSummary) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for part in summary.parts:
        for statement in part.statements:
            grouped.setdefault(statement.label, []).append(statement.text)
    return grouped


def _text(summary: ExecutiveSummary) -> str:
    return "\n".join(
        f"{statement.label}: {statement.text}"
        for part in summary.parts
        for statement in part.statements
    )


@pytest.mark.parametrize("path", _ALL_RECORDS, ids=lambda path: path.stem)
def test_summary_has_exactly_three_parts_in_order(path: Path) -> None:
    summary = build_executive_summary(_record(path))

    assert [part.title for part in summary.parts] == list(PART_TITLES)
    assert len(summary.parts) == 3
    for part in summary.parts:
        assert part.statements, part.title
        for statement in part.statements:
            assert statement.label and statement.text, (part.title, statement)
    assert summary.record_content_identity == _record(path)["record_content_identity"]
    assert summary.vocabulary_version == VOCABULARY_VERSION


@pytest.mark.parametrize("path", _ALL_RECORDS, ids=lambda path: path.stem)
def test_summary_part_tells_the_task_the_result_what_is_next_and_who_decides(path: Path) -> None:
    summary = build_executive_summary(_record(path))

    assert [statement.label for statement in summary.parts[0].statements] == [
        "The task",
        "The result",
        "What happens next",
        "Who decides",
    ]
    assert summary.parts[0].statements[3].text.startswith(DECISION_OWNER_STATEMENT)


def test_summary_states_the_indicated_option_by_its_authored_name() -> None:
    summary = build_executive_summary(_record())
    statements = _statements(summary)

    assert statements["The task"] == ["Review one bounded synthetic case."]
    assert statements["The result"] == [
        "The evidence indicates an option, subject to named conditions. The indicated option "
        "is AI inside a fixed workflow: Synthetic fixed."
    ]
    assert statements["What happens next"][0].startswith(
        "Before the indicated option can be relied on: Verify production capacity before adoption."
    )
    assert statements["What happens next"][0].endswith(
        "Settled by: Run the named production-capacity test."
    )
    assert statements["Who decides"] == [
        f"{DECISION_OWNER_STATEMENT} The accountable owner is Synthetic owner."
    ]


def test_summary_states_an_abstention_and_what_is_already_determined() -> None:
    """The acceptance record: an abstaining result that still carries a stop condition."""
    summary = build_executive_summary(_record(_ABSTENTION_RECORD))
    statements = _statements(summary)

    assert statements["The result"] == [
        "More evidence is needed before an option can be indicated."
    ]
    assert statements["What happens next"][0].startswith(
        "Record the information listed under Result and reasoning"
    )
    assert statements["Already determined"] == [
        "Ruled out: people do the work. Still open: AI inside a fixed workflow."
    ]
    assert statements["Absolute stop condition"] == [
        "The fictional disposition would be released without approval. Then: Release is "
        "prohibited until a fictional approver accepts it."
    ]
    assert statements["Person-required step"] == [
        "Approve the fictional disposition before release. When: Immediately before "
        "release-disposition. Who: Fictional approver."
    ]
    settling = statements["What would settle the rest"]
    assert len(settling) == 2
    assert settling[0].startswith(
        "The test of Fictional fixed AI workflow against Meet required quality has no "
        "recorded result."
    )


def test_summary_reports_a_no_permissible_candidate_outcome() -> None:
    record = _record()
    assessment = cast(dict[str, Any], record["assessment"])
    assessment["recommended_class"] = None
    assessment["verdict"] = "no-permissible-candidate"
    assessment["unmet_conditions"] = []

    statements = _statements(build_executive_summary(record))

    assert statements["The result"] == [
        "No represented option meets the required outcomes and constraints."
    ]
    assert statements["What happens next"][0].startswith(
        "No option considered can be indicated under the rules"
    )


def test_business_analysis_carries_the_four_value_statements_and_the_process_view() -> None:
    summary = build_executive_summary(_record(_ABSTENTION_RECORD))
    labels = [statement.label for statement in summary.parts[1].statements]

    assert labels == [
        "How much work is affected",
        "What hurts today",
        "What an error costs",
        "Why technology may be the limit",
        "How the work runs today",
        "Who takes part",
        "Accountable owner",
        "Step 1",
        "Step 2",
    ]
    statements = _statements(summary)
    assert statements["How much work is affected"] == ["Material volume."]
    assert statements["Why technology may be the limit"] == ["Current tooling limits retrieval."]
    assert statements["How the work runs today"] == [
        "It starts when: A complete case arrives. It is complete when: An approved disposition "
        "is recorded."
    ]
    assert statements["Who takes part"] == ["Reviewer, Approver."]
    assert statements["Step 1"] == [
        "Prepare the bounded disposition. This step is not consequential. No person-required "
        "step or absolute stop condition binds this step."
    ]
    assert statements["Step 2"] == [
        "Release the approved disposition. This step is consequential. A person must perform "
        "or confirm this step: Approve the fictional disposition before release (Fictional "
        "approver). It stops if: The fictional disposition would be released without approval."
    ]


def test_every_option_carries_its_flags_in_plain_language() -> None:
    summary = build_executive_summary(_record(_ABSTENTION_RECORD))
    options = _statements(summary)["Option"]

    assert len(options) == 2
    assert options[0].startswith(
        "Fictional human review. People follow the bounded review procedure using the existing "
        "register. Kind: people do the work. Standing: ruled out. Stop flag (framework rule 2): "
        "The recorded "
        "evidence shows Fictional human review does not reach the required outcome Meet "
        "required quality. The option cannot be the indicated option. Fit flag (framework rule 2):"
    )
    assert options[1].startswith(
        "Fictional fixed AI workflow. Code fixes the path while a model assists within the "
        "bounded preparation action. Kind: AI inside a fixed workflow. Standing: still open. "
        "Gap flag (framework rule 2): The test of Fictional fixed AI workflow against Meet "
        "required quality has no recorded result. The result cannot be reached until this is "
        "recorded. Fit flag (framework rule 2):"
    )
    # The same rule reaching the same option twice is told once.
    assert options[1].count("Gap flag (framework rule 2):") == 1
    whole = _statements(summary)["The options as a whole"]
    assert whole == [
        "Gap flag (framework rule 8): The comparison of Fictional fixed AI workflow with Fictional "
        "human review on "
        "quality of the outcome has no recorded result. The result cannot be reached until this "
        "is recorded."
    ]
    legend = _statements(summary)["How to read the flags"][0]
    for flag, meaning in FLAG_MEANINGS.items():
        assert f"{flag.capitalize()} flag: {meaning}" in legend


def test_absent_dossier_parts_are_stated_as_not_yet_recorded_rather_than_invented() -> None:
    summary = build_executive_summary(_record(_INCOMPLETE_RECORD))
    statements = _statements(summary)

    assert statements["The task"] == ["The task is not yet recorded."]
    assert statements["Who decides"] == [DECISION_OWNER_STATEMENT]
    assert [statement.label for statement in summary.parts[1].statements] == [
        "The business case",
        "How the work runs today",
    ]
    assert statements["The business case"] == ["Not yet recorded."]
    assert statements["Options considered"] == ["No options are recorded yet."]
    assert statements["Stop conditions and person-required steps"] == ["Not yet recorded."]
    assert statements["Already determined"] == ["Nothing is determined yet."]
    assert statements["The options as a whole"][0].startswith(
        "Gap flag (framework rule 1): The dossier does not bound the task"
    )
    assert len(statements["What would settle the rest"]) == 6
    assert statements["What would settle the rest"][-1] == (
        "A required observation is missing. Settled by: Run the required synthetic observation."
    )


def test_a_non_decisive_gap_is_neither_a_flag_nor_something_to_settle() -> None:
    record = _record(_ABSTENTION_RECORD)
    baseline = _text(build_executive_summary(record))
    cast(list[Any], record["unresolved_gaps"]).append(
        {
            "consequence": "The unknown comparison does not alter the verdict.",
            "counterpart": "counterfactual verdict: conditional",
            "effect": "non-decisive",
            "evidence_ids": ["decision-observed"],
            "field": "$.candidate_comparison.comparisons[0].dimensions.cost.result",
            "message": "Every admissible value preserves the verdict under the packaged rules.",
            "remediation": "Resolve the comparison when useful.",
            "requirement": "FR-008/FR-009",
            "rule_id": "comparison-result-unknown-non-decisive",
            "source": "prerequisite",
        }
    )

    assert _text(build_executive_summary(record)) == baseline


def test_summary_speaks_only_in_fixed_text_and_record_content() -> None:
    """FR-017: nothing is stated that the record does not contain.

    Every statement is fixed vocabulary text with authored record content
    embedded. Removing every record string, every vocabulary phrase, and the
    fixed connective text must leave nothing behind: no invented fact, count, or
    name. Numbers in particular can only come from the record itself.
    """
    for path in _ALL_RECORDS:
        record = _record(path)
        summary = build_executive_summary(record)
        available = _record_strings(masked_decision_record_view(record))
        text = _text(summary)
        record_digits = {digit for value in available for digit in re.findall(r"\d+", value)}
        assert set(re.findall(r"\d+", text)) <= record_digits | {"1", "2", "3"}, path.stem
        for statement in (s for part in summary.parts for s in part.statements):
            quoted = [value for value in available if len(value) > 3 and value in statement.text]
            assert quoted or statement.label in {
                "The task",
                "Who decides",
                "What happens next",
                "The business case",
                "How the work runs today",
                "Options considered",
                "Stop conditions and person-required steps",
                "Already determined",
                "What would settle the rest",
                "How to read the flags",
                "The result",
            }, (statement.label, statement.text)


def test_fixed_text_avoids_every_excluded_word() -> None:
    """NFR-011: the register belongs to the tool; authored words are the author's."""
    for path in _ALL_RECORDS:
        record = _record(path)
        summary = build_executive_summary(record)
        fixed = _text(summary)
        # Authored text is embedded as a sentence or a clause: capitalised, or
        # without its closing full stop, so it is removed in either form.
        strings = sorted(_record_strings(masked_decision_record_view(record)), key=len)
        for value in reversed(strings):  # longest first, so a phrase is removed whole
            if len(value) > 3:
                fixed = re.sub(re.escape(value.rstrip(".")), " ", fixed, flags=re.IGNORECASE)
        assert excluded_words_in(fixed) == (), (path.stem, excluded_words_in(fixed))
        assert excluded_words_in(" ".join(PART_TITLES)) == ()


def test_changing_an_authored_fact_changes_only_the_statements_that_quote_it() -> None:
    record = _record(_ABSTENTION_RECORD)
    before = build_executive_summary(record)
    cast(dict[str, Any], record["dossier"])["task"]["operation"] = "Handle one synthetic claim."

    after = build_executive_summary(record)

    changed = [
        (b.label, a.text)
        for pb, pa in zip(before.parts, after.parts, strict=True)
        for b, a in zip(pb.statements, pa.statements, strict=True)
        if b != a
    ]
    assert changed == [("The task", "Handle one synthetic claim.")]


def test_summary_masks_authored_values_and_is_idempotent() -> None:
    record = _record()
    dossier = cast(dict[str, Any], record["dossier"])
    dossier["case"]["title"] = "Card 4111 1111 1111 1111 and api_key: AKIAIOSFODNN7EXAMPLE"
    dossier["task"]["operation"] = "Call 4111 1111 1111 1111 with api_key: AKIAIOSFODNN7EXAMPLE"
    record.pop("masking", None)

    summary = build_executive_summary(record)
    text = summary.case_title + _text(summary)

    assert "4111 1111 1111 1111" not in text
    assert "AKIAIOSFODNN7EXAMPLE" not in text
    assert "[ARCHSIFT-MASKED:payment-card]" in summary.case_title
    assert "[ARCHSIFT-MASKED:credential]" in _statements(summary)["The task"][0]
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
