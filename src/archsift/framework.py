"""The decision framework card (FR-020).

The card is a reader-facing rendering of the ruleset for readers without
technical background: the four decision questions, the five options in order
of runtime freedom, the five flags, the numbered framework rules, the no-tally
statement, and the framework version. It is derived from the ruleset and the
vocabulary only, states no rule the ruleset does not contain, presents no
score, total, weight, or case-specific ranking, and never participates in
evaluation. Every internal rule maps to exactly one framework rule, so a flag
in a report can cite a framework rule number without naming an internal
identifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from archsift import vocabulary
from archsift.rules import RULESET_VERSION
from archsift.validation import ControlClass, DecisionArea
from archsift.vocabulary import (
    FLAG_MEANINGS,
    FLAGS,
    OPTION_SENTENCES,
    OPTIONS,
    QUESTION_SENTENCES,
    QUESTIONS,
    RESULT_RESOLUTION,
    FrameworkRule,
    validate_vocabulary,
)

CARD_TITLE: Final = "How the result was reached"
RESULT_GROUP_TITLE: Final = "How the result follows from the flags"


@dataclass(frozen=True, slots=True)
class NamedSentence:
    """One fixed reader-facing name with one plain sentence."""

    name: str
    sentence: str


@dataclass(frozen=True, slots=True)
class RuleGroup:
    """The framework rules serving one decision question, or result resolution."""

    title: str
    rules: tuple[FrameworkRule, ...]


@dataclass(frozen=True, slots=True)
class FrameworkCard:
    """The complete decision framework card for one ruleset and vocabulary."""

    framework_version: str
    ruleset_version: str
    vocabulary_version: str
    questions: tuple[NamedSentence, ...]
    options: tuple[NamedSentence, ...]
    flags: tuple[NamedSentence, ...]
    groups: tuple[RuleGroup, ...]
    statement: str


def build_framework_card() -> FrameworkCard:
    """Build the framework card from the ruleset and the validated vocabulary."""
    validate_vocabulary()
    # The versioned elements are read from the vocabulary module at call time,
    # so the card is addressed by the versions in force when it is built.
    framework_rules = vocabulary.FRAMEWORK_RULES
    groups: list[RuleGroup] = []
    for area in DecisionArea:
        rules = tuple(rule for rule in framework_rules if rule.group is area)
        if rules:
            groups.append(RuleGroup(QUESTIONS[area], rules))
    result_rules = tuple(rule for rule in framework_rules if rule.group == RESULT_RESOLUTION)
    if result_rules:
        groups.append(RuleGroup(RESULT_GROUP_TITLE, result_rules))
    return FrameworkCard(
        framework_version=vocabulary.FRAMEWORK_VERSION,
        ruleset_version=RULESET_VERSION,
        vocabulary_version=vocabulary.VOCABULARY_VERSION,
        questions=tuple(
            NamedSentence(QUESTIONS[area], QUESTION_SENTENCES[area]) for area in DecisionArea
        ),
        options=tuple(
            NamedSentence(OPTIONS[control_class], OPTION_SENTENCES[control_class])
            for control_class in ControlClass
        ),
        # FLAGS is ordered as the card reads them: stop, gap, condition, fit, noted.
        flags=tuple(NamedSentence(flag, FLAG_MEANINGS[flag]) for flag in FLAGS.values()),
        groups=tuple(groups),
        statement=vocabulary.FRAMEWORK_STATEMENT,
    )


def card_lines(card: FrameworkCard) -> list[str]:
    """Render the card as plain text lines, in its fixed order."""
    lines = [f"{CARD_TITLE} (framework {card.framework_version})"]
    lines.append("The four questions:")
    lines.extend(f"- {item.name} {item.sentence}" for item in card.questions)
    lines.append("The five options, from least to most run-time freedom:")
    lines.extend(f"- {item.name}: {item.sentence}" for item in card.options)
    lines.append("The flags:")
    lines.extend(f"- {item.name} flag: {item.sentence}" for item in card.flags)
    lines.append("The framework rules:")
    for group in card.groups:
        lines.append(f"{group.title}")
        lines.extend(f"  Rule {rule.number}. {rule.sentence}" for rule in group.rules)
    lines.append(card.statement)
    return lines
