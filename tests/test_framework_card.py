"""The decision framework card and its total rule mapping (FR-020)."""

from __future__ import annotations

import json
import re
from types import MappingProxyType

import pytest

from archsift import vocabulary
from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.framework import (
    CARD_TITLE,
    RESULT_GROUP_TITLE,
    build_framework_card,
    card_lines,
)
from archsift.rules import RULESET_VERSION, list_rules
from archsift.validation import ControlClass, DecisionArea
from archsift.vocabulary import (
    FRAMEWORK_MAPPING,
    FRAMEWORK_RULE_LIMIT,
    FRAMEWORK_RULES,
    FRAMEWORK_STATEMENT,
    FRAMEWORK_VERSION,
    FrameworkRule,
    VocabularyError,
    excluded_words_in,
    framework_rule_number,
    validate_vocabulary,
    vocabulary_payload,
)

_RANKING = re.compile(r"\b(scores?|totals?|weights?|rank(?:ing|ed)?|percent(?:age)?)\b|%")


def test_card_carries_exactly_its_six_elements_in_order() -> None:
    card = build_framework_card()

    assert card.framework_version == FRAMEWORK_VERSION == "1.0.0"
    assert card.ruleset_version == RULESET_VERSION
    assert card.vocabulary_version == vocabulary.VOCABULARY_VERSION
    assert [item.name for item in card.questions] == [
        vocabulary.QUESTIONS[area] for area in DecisionArea
    ]
    assert [item.name for item in card.options] == [
        vocabulary.OPTIONS[control_class] for control_class in ControlClass
    ]
    assert [item.name for item in card.flags] == ["stop", "gap", "condition", "fit", "noted"]
    assert [group.title for group in card.groups] == [
        *(vocabulary.QUESTIONS[area] for area in DecisionArea),
        RESULT_GROUP_TITLE,
    ]
    numbers = [rule.number for group in card.groups for rule in group.rules]
    assert numbers == list(range(1, len(FRAMEWORK_RULES) + 1))
    assert len(numbers) <= FRAMEWORK_RULE_LIMIT
    assert card.statement == FRAMEWORK_STATEMENT
    assert "not counted or totalled" in card.statement
    assert "never offset by fit flags" in card.statement
    assert card.statement.endswith(vocabulary.DECISION_OWNER_STATEMENT)
    for item in (*card.questions, *card.options, *card.flags):
        assert item.sentence.endswith(".") and item.sentence[0].isupper(), item


def test_card_text_presents_no_score_ranking_or_internal_identifier() -> None:
    lines = card_lines(build_framework_card())
    text = "\n".join(lines)

    assert lines[0] == f"{CARD_TITLE} (framework {FRAMEWORK_VERSION})"
    assert lines[-1] == FRAMEWORK_STATEMENT
    # "totalled" in the no-tally statement is the one permitted form.
    assert _RANKING.search(text.lower()) is None, _RANKING.search(text.lower())
    for rule in list_rules():
        assert rule.id not in text, rule.id
    for token in (
        *(area.value for area in DecisionArea),
        *(control_class.value for control_class in ControlClass),
        "require-evidence",
        "support-candidate",
        "constrain-autonomy",
        "non-decisive",
        "dossier",
        "verdict",
    ):
        assert re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", text) is None, token
    assert excluded_words_in(text) == ()
    # Every framework rule states a flag or how the result follows from the flags.
    for rule in FRAMEWORK_RULES:
        assert " flag" in rule.sentence or "indicated option" in rule.sentence, rule.number


def test_every_internal_rule_maps_to_exactly_one_framework_rule_and_back() -> None:
    catalog = {rule.id for rule in list_rules()}

    assert set(FRAMEWORK_MAPPING) == catalog
    numbers = {rule.number for rule in FRAMEWORK_RULES}
    assert set(FRAMEWORK_MAPPING.values()) == numbers
    for rule_id in sorted(catalog):
        assert framework_rule_number(rule_id) == FRAMEWORK_MAPPING[rule_id]
    # A verdict rule maps under result resolution; a candidate test rule under its question.
    assert framework_rule_number("verdict-insufficient-evidence") == 10
    assert framework_rule_number("binding-outcome-failed") == 2
    assert framework_rule_number("mandatory-human-control-retained") == 6
    with pytest.raises(VocabularyError, match="no-such-rule"):
        framework_rule_number("no-such-rule")


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda: MappingProxyType(
                {k: v for k, v in FRAMEWORK_MAPPING.items() if k != "task-boundary-missing"}
            ),
            "task-boundary-missing",
        ),
        (
            lambda: MappingProxyType({**FRAMEWORK_MAPPING, "task-boundary-missing": 99}),
            "unknown framework rule 99",
        ),
        (
            lambda: MappingProxyType({**FRAMEWORK_MAPPING, "invented-rule": 1}),
            "unknown rule 'invented-rule'",
        ),
    ],
    ids=["unmapped-rule", "unknown-number", "unknown-rule"],
)
def test_vocabulary_fails_closed_on_a_broken_mapping(
    monkeypatch: pytest.MonkeyPatch, mutate: object, match: str
) -> None:
    monkeypatch.setattr(vocabulary, "FRAMEWORK_MAPPING", mutate())  # type: ignore[operator]

    with pytest.raises(VocabularyError, match=match):
        validate_vocabulary()
    with pytest.raises(VocabularyError):
        build_framework_card()


def test_vocabulary_fails_closed_on_a_thirteenth_rule_an_orphan_rule_or_an_excluded_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extra = tuple(
        FrameworkRule(number, vocabulary.RESULT_RESOLUTION, "Synthetic flag sentence.")
        for number in range(len(FRAMEWORK_RULES) + 1, FRAMEWORK_RULE_LIMIT + 2)
    )
    monkeypatch.setattr(vocabulary, "FRAMEWORK_RULES", (*FRAMEWORK_RULES, *extra))
    with pytest.raises(VocabularyError, match="at most 12"):
        validate_vocabulary()

    orphan = FrameworkRule(len(FRAMEWORK_RULES) + 1, vocabulary.RESULT_RESOLUTION, "A flag.")
    monkeypatch.setattr(vocabulary, "FRAMEWORK_RULES", (*FRAMEWORK_RULES, orphan))
    with pytest.raises(VocabularyError, match="maps to no internal rule"):
        validate_vocabulary()

    reworded = (
        FrameworkRule(1, DecisionArea.PROBLEM_VALUE, "The tool approves the option."),
        *FRAMEWORK_RULES[1:],
    )
    monkeypatch.setattr(vocabulary, "FRAMEWORK_RULES", reworded)
    with pytest.raises(VocabularyError, match="approves"):
        validate_vocabulary()


def test_rules_surface_carries_the_card_and_the_mapping(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["rules", "--json"]) == ExitCode.SUCCESS
    payload = json.loads(capsys.readouterr().out)
    framework = payload["vocabulary"]["framework"]

    assert payload["ruleset_version"] == RULESET_VERSION
    assert payload["vocabulary"]["version"] == vocabulary.VOCABULARY_VERSION
    assert framework["version"] == FRAMEWORK_VERSION
    assert framework["rule_limit"] == FRAMEWORK_RULE_LIMIT
    assert [rule["number"] for rule in framework["rules"]] == list(
        range(1, len(FRAMEWORK_RULES) + 1)
    )
    assert {rule["group"] for rule in framework["rules"]} == {
        *(area.value for area in DecisionArea),
        vocabulary.RESULT_RESOLUTION,
    }
    assert framework["mapping"] == dict(sorted(FRAMEWORK_MAPPING.items()))
    assert set(framework["mapping"]) == {rule["id"] for rule in payload["rules"]}
    assert framework["statement"] == FRAMEWORK_STATEMENT
    assert set(framework["question_sentences"]) == {area.value for area in DecisionArea}
    assert set(framework["option_sentences"]) == {c.value for c in ControlClass}

    assert main(["rules"]) == ExitCode.SUCCESS
    human = capsys.readouterr().out
    lines = card_lines(build_framework_card())
    for line in lines:
        assert line in human, line
    for rule in list_rules():
        assert f"Framework rule {FRAMEWORK_MAPPING[rule.id]}." in next(
            candidate for candidate in human.splitlines() if candidate.startswith(f"{rule.id} [")
        )

    assert main(["rules", "--quiet"]) == ExitCode.SUCCESS
    assert capsys.readouterr().out == ""


def test_card_payload_is_deterministic_and_addressed_by_its_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = json.dumps(vocabulary_payload()["framework"], sort_keys=True)
    assert json.dumps(vocabulary_payload()["framework"], sort_keys=True) == before

    monkeypatch.setattr(vocabulary, "FRAMEWORK_VERSION", "9.9.9-test")
    after = vocabulary_payload()["framework"]
    assert after["version"] == "9.9.9-test"
    assert json.dumps(after, sort_keys=True) != before
    assert build_framework_card().framework_version == "9.9.9-test"
