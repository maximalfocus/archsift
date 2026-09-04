"""Versioned plain-language vocabulary for reader-facing text (NFR-011).

Every internal term a reader-facing output can present maps here to one
reader-facing phrase in a neutral register: findings render as flags on
options, never as an act of the tool upon the case. The vocabulary is a
rendering input only; it never participates in a decision record's identity.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from archsift.decision import ArchitectureVerdict, EvidenceState
from archsift.rules import RuleEffect, list_rules
from archsift.validation import ControlClass, DecisionArea, EvidenceKind

VOCABULARY_VERSION: Final = "1.1.0"
VOCABULARY_SPECIFICATION: Final = "docs/vocabulary-v1.1.0.md"

# Words that present the tool as a judge. Their inflections are excluded too.
EXCLUDED_WORDS: Final[tuple[str, ...]] = (
    "verify",
    "validate",
    "approve",
    "reject",
    "certify",
    "recommend",
    "veto",
)
_EXCLUDED_PATTERN: Final = re.compile(
    r"\b(verif\w*|validat\w*|approv\w*|reject\w*|certif\w*|recommend\w*|veto\w*)\b",
    re.IGNORECASE,
)


class VocabularyError(ValueError):
    """A reader-facing phrase is missing or breaks the neutral register."""


@dataclass(frozen=True, slots=True)
class RulePhrases:
    """Reader-facing forms of one rule's message, consequence, and remediation.

    ``message`` is a template: ``{name}`` placeholders name authored elements by
    their authored name or description at rendering time, never by identifier.
    """

    flag: str
    message: str
    consequence: str
    remediation: str


FLAGS: Final[Mapping[RuleEffect, str]] = MappingProxyType(
    {
        RuleEffect.BLOCK: "stop",
        RuleEffect.REQUIRE_EVIDENCE: "gap",
        RuleEffect.CONSTRAIN_AUTONOMY: "condition",
        RuleEffect.SUPPORT_CANDIDATE: "fit",
        RuleEffect.NON_DECISIVE: "noted",
    }
)

FLAG_MEANINGS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "stop": "The option cannot be the indicated option under the rules.",
        "gap": "Material evidence is missing; the option stays open until it is recorded.",
        "condition": "The option stays open only with the named person-required step kept.",
        "fit": (
            "The evidence supports the option on this point; it never outweighs a stop or a gap."
        ),
        "noted": "Recorded for completeness; it does not change the option's standing.",
    }
)

RESULT_NAME: Final = "result"
INDICATED_OPTION: Final = "indicated option"
DECISION_OWNER_STATEMENT: Final = "The decision rests with the accountable owner."

VERDICTS: Final[Mapping[ArchitectureVerdict, str]] = MappingProxyType(
    {
        ArchitectureVerdict.SUPPORTED: (
            "the evidence indicates the least complex option that meets every requirement"
        ),
        ArchitectureVerdict.CONDITIONAL: (
            "the evidence indicates an option, subject to named conditions"
        ),
        ArchitectureVerdict.INSUFFICIENT_EVIDENCE: (
            "more evidence is needed before an option can be indicated"
        ),
        ArchitectureVerdict.NO_PERMISSIBLE_CANDIDATE: (
            "no represented option meets the required outcomes and constraints"
        ),
        ArchitectureVerdict.NO_TECHNOLOGY_CHANGE: (
            "the evidence indicates keeping the work with people or redesigning the process, with "
            "no new technology"
        ),
    }
)

EVIDENCE_STATES: Final[Mapping[EvidenceState, str]] = MappingProxyType(
    {
        EvidenceState.COMPLETE: "the evidence needed for this result is complete",
        EvidenceState.INCOMPLETE: "material evidence is still missing",
    }
)

OPTIONS: Final[Mapping[ControlClass, str]] = MappingProxyType(
    {
        ControlClass.HUMAN_OWNED_WORK: "people do the work",
        ControlClass.PROCESS_REDESIGN: "redesign the process first",
        ControlClass.DETERMINISTIC_AUTOMATION: "rule-based automation",
        ControlClass.FIXED_AI_WORKFLOW: "AI inside a fixed workflow",
        ControlClass.AGENTIC_CONTROL: "AI that chooses its own steps",
    }
)

EVIDENCE_KINDS: Final[Mapping[EvidenceKind, str]] = MappingProxyType(
    {
        EvidenceKind.OBSERVED: "seen and recorded",
        EvidenceKind.ASSUMPTION: "assumed",
        EvidenceKind.ESTIMATE: "estimated",
        EvidenceKind.MISSING: "not yet available",
    }
)

QUESTIONS: Final[Mapping[DecisionArea, str]] = MappingProxyType(
    {
        DecisionArea.PROBLEM_VALUE: "Is there a problem worth solving?",
        DecisionArea.AGENCY_NECESSITY: "Must a model choose the steps at run time?",
        DecisionArea.AUTONOMY_PERMISSION: (
            "Which actions may be handed over, and which must a person keep?"
        ),
        DecisionArea.COMPARATIVE_FIT: "Which option fits best against the simpler alternatives?",
    }
)

# Reader-facing names for the structured questions, dimensions, roles, results,
# answers, and states that a narrative presents. Keys are the dossier field or
# token; every value is a fixed phrase in the neutral register.
QUESTION_FIELDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "execution_steps_predefinable": "Can the steps be fixed in advance?",
        "step_count_or_order_predictable": "Is the number and order of steps predictable?",
        "runtime_tool_choice_required": "Must a tool be chosen at run time?",
        "runtime_replanning_required": "Must the plan change at run time?",
        "environmental_feedback_available": "Does the environment give feedback to act on?",
        "completion_independently_verifiable": "Can completion be checked independently?",
        "effects_independently_verifiable": "Can the effects be checked independently?",
        "fixed_workflow_sufficient": "Is a fixed sequence of steps enough?",
        "actions_reversible": "Can the actions be undone?",
        "failure_blast_radius_bounded": "Is the damage from a failure bounded?",
        "regulatory_automation_permitted": "Do the rules that govern the task allow automation?",
        "data_confidence_sufficient": "Is the data trustworthy enough?",
        "accountable_owner_assigned": "Is an accountable owner assigned?",
        "decision_path_auditable": "Can the decision path be audited?",
        "timely_human_intervention_available": "Can a person step in in time?",
        "safe_degradation_available": "Can the task degrade safely?",
    }
)

DIMENSIONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "outcome_quality": "quality of the outcome",
        "difficult_case_performance": "handling of difficult cases",
        "cost": "cost",
        "latency": "speed",
        "human_effort": "human effort",
        "integration_burden": "integration effort",
        "security_exposure": "security exposure",
        "failure_impact": "impact of failure",
        "operability": "ease of operation",
        "evaluation_burden": "effort to evaluate",
        "maintainability": "ease of maintenance",
    }
)

ROLES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "current-baseline": "the current way of working",
        "proposed": "the proposal",
        "strongest-simpler": "the strongest simpler alternative",
        "agentic-comparator": "the comparison with AI that chooses its own steps",
    }
)

TEST_RESULTS: Final[Mapping[str, str]] = MappingProxyType(
    {"meets": "meets it", "fails": "does not meet it", "unknown": "not yet known"}
)

COMPARISON_RESULTS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "better": "better",
        "equivalent": "about the same",
        "worse": "worse",
        "unknown": "not yet known",
    }
)

ANSWERS: Final[Mapping[str, str]] = MappingProxyType(
    {"yes": "yes", "no": "no", "unknown": "not yet known"}
)

STOP_CONDITION_STATES: Final[Mapping[str, str]] = MappingProxyType(
    {"active": "in force", "inactive": "not in force", "unknown": "not yet known"}
)

CONDITION_STATES: Final[Mapping[str, str]] = MappingProxyType(
    {"met": "met", "unmet": "not yet met"}
)

AUTHORS: Final[Mapping[str, str]] = MappingProxyType(
    {"accountable-person": "an accountable person", "assistant": "an assisting author"}
)

TARGET_KINDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "quantified": "a numeric target",
        "directional": "a direction of change",
        "no-regression": "no worse than today",
    }
)

DISPOSITIONS: Final[Mapping[str, str]] = MappingProxyType(
    {"eliminated": "ruled out", "undetermined": "still open", "survives": "still in play"}
)

_PROCEED = "The result cannot be reached until this is recorded."
_UNDETERMINED = "The option stays open until this is recorded."
_ELIMINATED = "The option cannot be the indicated option."
_FIT = "This supports the option; it never outweighs a stop or a gap."
_NOTED = "Recorded for completeness; nothing changes for the option."

RULES: Final[Mapping[str, RulePhrases]] = MappingProxyType(
    {
        "active-veto-applicability-missing": RulePhrases(
            "gap",
            "The absolute stop condition {condition} touches an action of {candidate}, but the "
            "dossier does not say which options it stops.",
            _UNDETERMINED,
            "State which options the stop condition rules out.",
        ),
        "active-veto-blocks-candidate": RulePhrases(
            "stop",
            "The absolute stop condition {condition} rules out {candidate} on the actions they "
            "share.",
            _ELIMINATED,
            "Keep the stop condition as a design input; consider an option it does not rule out.",
        ),
        "agency-answer-unknown": RulePhrases(
            "gap",
            "The answer to the run-time question {question} is not recorded.",
            _PROCEED,
            "Record a yes or no answer with the evidence behind it.",
        ),
        "agency-necessity-contradiction": RulePhrases(
            "gap",
            "The dossier says a fixed sequence of steps is enough and also that the steps must be "
            "chosen at run time.",
            _PROCEED,
            "Correct one of the two answers, or record the evidence that settles the conflict.",
        ),
        "agency-necessity-missing": RulePhrases(
            "gap",
            "The dossier does not answer whether a model must choose the steps at run time.",
            _PROCEED,
            "Record the run-time questions with their evidence.",
        ),
        "agentic-agency-answer-unknown": RulePhrases(
            "gap",
            "For {candidate}, the run-time question {question} has no recorded answer.",
            _UNDETERMINED,
            "Record a yes or no answer with the evidence behind it.",
        ),
        "agentic-agency-fact-non-decisive": RulePhrases(
            "noted",
            "The run-time fact {question} is recorded for {candidate} and does not change its "
            "standing.",
            _NOTED,
            "No action is needed.",
        ),
        "agentic-agency-necessity-missing": RulePhrases(
            "gap",
            "For {candidate}, the run-time questions are not recorded.",
            _UNDETERMINED,
            "Record the run-time questions with their evidence.",
        ),
        "agentic-credible-agency-evidence-missing": RulePhrases(
            "gap",
            "For {candidate}, the answer to {question} rests on an assumption or a known gap "
            "rather than an observation or a method-backed estimate.",
            _UNDETERMINED,
            "Cite an observation or a method-backed estimate, confirmed by an accountable person.",
        ),
        "agentic-credible-residual-evidence-missing": RulePhrases(
            "gap",
            "For {candidate}, the case {residual} that a fixed sequence cannot handle rests on an "
            "assumption or a known gap.",
            _UNDETERMINED,
            "Cite an observation or a method-backed estimate for that case.",
        ),
        "agentic-dynamic-execution-supports-agency": RulePhrases(
            "fit",
            "The recorded evidence shows the steps cannot be fixed in advance, which supports "
            "{candidate}.",
            _FIT,
            "No action is needed.",
        ),
        "agentic-feedback-supports-agency": RulePhrases(
            "fit",
            "The recorded evidence shows the environment gives feedback a model can act on, which "
            "supports {candidate}.",
            _FIT,
            "No action is needed.",
        ),
        "agentic-feedback-unavailable-blocks-candidate": RulePhrases(
            "stop",
            "The recorded evidence shows no environmental feedback is available, so {candidate} "
            "cannot operate as described.",
            _ELIMINATED,
            "Consider an option that does not depend on run-time feedback.",
        ),
        "agentic-fixed-workflow-insufficiency-supports-agency": RulePhrases(
            "fit",
            "The recorded evidence shows a fixed sequence of steps is not enough, which supports "
            "{candidate}; a concrete case is still required.",
            _FIT,
            "Record at least one concrete case a fixed sequence cannot handle.",
        ),
        "agentic-fixed-workflow-sufficient-blocks-candidate": RulePhrases(
            "stop",
            "The recorded evidence shows a fixed sequence of steps is enough, so {candidate} adds "
            "freedom the task does not need.",
            _ELIMINATED,
            "Consider the fixed-sequence option the evidence already supports.",
        ),
        "agentic-residual-case-missing": RulePhrases(
            "gap",
            "The dossier says a fixed sequence is not enough but records no concrete case that "
            "shows it.",
            _UNDETERMINED,
            "Record at least one concrete case a fixed sequence cannot handle.",
        ),
        "agentic-residual-case-supports-agency": RulePhrases(
            "fit",
            "The concrete case {residual} shows a fixed sequence is not enough, which supports "
            "{candidate}.",
            _FIT,
            "No action is needed.",
        ),
        "agentic-runtime-adaptation-missing": RulePhrases(
            "stop",
            "The recorded evidence shows no step needs to be chosen or re-planned at run time, so "
            "{candidate} is not needed.",
            _ELIMINATED,
            "Consider a fixed-sequence option.",
        ),
        "agentic-runtime-adaptation-supports-agency": RulePhrases(
            "fit",
            "The recorded evidence shows steps must be chosen or re-planned at run time, which "
            "supports {candidate}.",
            _FIT,
            "No action is needed.",
        ),
        "automation-authority-missing": RulePhrases(
            "gap",
            "The dossier does not say which actions {candidate} would carry out.",
            _UNDETERMINED,
            "List the actions the option would carry out and the person-required steps it keeps.",
        ),
        "autonomy-answer-unknown": RulePhrases(
            "gap",
            "The answer to the hand-over question {question} is not recorded.",
            _PROCEED,
            "Record a yes or no answer with the evidence behind it.",
        ),
        "autonomy-boundary-non-decisive": RulePhrases(
            "noted",
            "The stop condition or person-required step {boundary} does not apply to {candidate}.",
            _NOTED,
            "No action is needed.",
        ),
        "autonomy-permission-missing": RulePhrases(
            "gap",
            "The dossier does not answer which actions may be handed over and which a person must "
            "keep.",
            _PROCEED,
            "Record the hand-over questions, stop conditions, and person-required steps with "
            "their evidence.",
        ),
        "baseline-reference-unresolved": RulePhrases(
            "gap",
            "The required outcome {outcome} points to a current-state figure that is not recorded.",
            _PROCEED,
            "Record the current-state figure the outcome is measured against.",
        ),
        "baseline-retention-contradiction": RulePhrases(
            "gap",
            "The dossier declares that keeping the current way of working is intended, yet the "
            "evidence shows it misses the required outcome {outcome}.",
            _PROCEED,
            "Withdraw the declaration, or correct the outcome result if the evidence supports it.",
        ),
        "binding-constraint-failed": RulePhrases(
            "stop",
            "The recorded evidence shows {candidate} does not meet the binding constraint "
            "{constraint}.",
            _ELIMINATED,
            "Consider an option that meets the constraint, or record evidence that this one does.",
        ),
        "binding-constraint-met": RulePhrases(
            "fit",
            "The recorded evidence shows {candidate} meets the binding constraint {constraint}.",
            _FIT,
            "No action is needed.",
        ),
        "binding-outcome-failed": RulePhrases(
            "stop",
            "The recorded evidence shows {candidate} does not reach the required outcome "
            "{outcome}.",
            _ELIMINATED,
            "Consider an option that reaches the outcome, or record evidence that this one does.",
        ),
        "binding-outcome-met": RulePhrases(
            "fit",
            "The recorded evidence shows {candidate} reaches the required outcome {outcome}.",
            _FIT,
            "No action is needed.",
        ),
        "binding-outcome-missing": RulePhrases(
            "gap",
            "No required outcome is recorded, so there is nothing to measure an option against.",
            _PROCEED,
            "Record at least one required, measurable outcome.",
        ),
        "candidate-authority-class-contradiction": RulePhrases(
            "gap",
            "{candidate} keeps the work with people or redesigns the process, yet lists actions a "
            "machine would carry out.",
            _PROCEED,
            "Remove the machine action list from that option, or change the option's kind.",
        ),
        "candidate-comparison-missing": RulePhrases(
            "gap",
            "The dossier does not compare the options.",
            _PROCEED,
            "Record the options, their roles, their tests, and their pairwise comparisons.",
        ),
        "candidate-constraint-test-missing": RulePhrases(
            "gap",
            "{candidate} has not been tested against the constraint {constraint}.",
            _PROCEED,
            "Record whether the option meets the constraint, with evidence.",
        ),
        "candidate-outcome-test-missing": RulePhrases(
            "gap",
            "{candidate} has not been tested against the outcome {outcome}.",
            _PROCEED,
            "Record whether the option reaches the outcome, with evidence.",
        ),
        "candidate-problem-value-missing": RulePhrases(
            "gap",
            "The options cannot be tested because the outcomes and constraints are not recorded.",
            _PROCEED,
            "Record the outcomes and constraints first.",
        ),
        "candidate-role-incompatible": RulePhrases(
            "gap",
            "The role given to {candidate} does not match its kind.",
            _PROCEED,
            "Give each role to an option of a fitting kind.",
        ),
        "candidate-test-result-unknown": RulePhrases(
            "gap",
            "The test of {candidate} against {criterion} has no recorded result.",
            _PROCEED,
            "Record whether the option meets it, with evidence.",
        ),
        "comparison-reciprocity-contradiction": RulePhrases(
            "gap",
            "The comparison of {candidate} with {comparator} on {dimension} is recorded both ways "
            "in a way that cannot both be true.",
            _PROCEED,
            "Correct one direction of the comparison.",
        ),
        "comparison-result-unknown": RulePhrases(
            "gap",
            "The comparison of {candidate} with {comparator} on {dimension} has no recorded "
            "result.",
            _PROCEED,
            "Record whether the option is better, equivalent, or worse on that point, with "
            "evidence.",
        ),
        "comparison-result-unknown-non-decisive": RulePhrases(
            "noted",
            "The comparison of {candidate} with {comparator} on {dimension} is unknown, and no "
            "answer would change the result.",
            _NOTED,
            "No action is needed.",
        ),
        "credible-agency-evidence-missing": RulePhrases(
            "gap",
            "The answer to the run-time question {question} rests on an assumption or a known gap "
            "rather than an observation or a method-backed estimate.",
            _PROCEED,
            "Cite an observation or a method-backed estimate, confirmed by an accountable person.",
        ),
        "credible-authority-evidence-missing": RulePhrases(
            "gap",
            "The actions {candidate} would carry out rest on an assumption or a known gap rather "
            "than an observation or a method-backed estimate.",
            _UNDETERMINED,
            "Cite an observation or a method-backed estimate, confirmed by an accountable person.",
        ),
        "credible-autonomy-evidence-missing": RulePhrases(
            "gap",
            "The answer to the hand-over question {question} rests on an assumption or a known "
            "gap rather than an observation or a method-backed estimate.",
            _PROCEED,
            "Cite an observation or a method-backed estimate, confirmed by an accountable person.",
        ),
        "credible-baseline-missing": RulePhrases(
            "gap",
            "The current-state figure for the required outcome {outcome} rests on an assumption "
            "or a known gap rather than an observation or a method-backed estimate.",
            _PROCEED,
            "Measure the current state, or record a structured elicitation for an outcome that is "
            "not a numeric target.",
        ),
        "credible-candidate-test-evidence-missing": RulePhrases(
            "gap",
            "The test of {candidate} against {criterion} rests on an assumption or a known gap "
            "rather than an observation or a method-backed estimate.",
            _PROCEED,
            "Cite an observation or a method-backed estimate, confirmed by an accountable person.",
        ),
        "credible-comparison-evidence-missing": RulePhrases(
            "gap",
            "The comparison of {candidate} with {comparator} on {dimension} rests on an "
            "assumption or a known gap rather than an observation or a method-backed estimate.",
            _PROCEED,
            "Cite an observation or a method-backed estimate, confirmed by an accountable person.",
        ),
        "credible-hard-veto-evidence-missing": RulePhrases(
            "gap",
            "The absolute stop condition {condition} rests on an assumption or a known gap rather "
            "than an observation or a method-backed estimate.",
            _PROCEED,
            "Cite an observation or a method-backed estimate, confirmed by an accountable person.",
        ),
        "credible-human-control-evidence-missing": RulePhrases(
            "gap",
            "The person-required step {control} rests on an assumption or a known gap rather than "
            "an observation or a method-backed estimate.",
            _PROCEED,
            "Cite an observation or a method-backed estimate, confirmed by an accountable person.",
        ),
        "credible-residual-case-evidence-missing": RulePhrases(
            "gap",
            "The case {residual} that a fixed sequence cannot handle rests on an assumption or a "
            "known gap rather than an observation or a method-backed estimate.",
            _PROCEED,
            "Cite an observation or a method-backed estimate, confirmed by an accountable person.",
        ),
        "credible-strongest-simpler-evidence-missing": RulePhrases(
            "gap",
            "The choice of {candidate} as the strongest simpler alternative rests on an "
            "assumption or a known gap rather than an observation or a method-backed estimate.",
            _PROCEED,
            "Cite an observation or a method-backed estimate, confirmed by an accountable person.",
        ),
        "elicited-baseline-quantified-target": RulePhrases(
            "gap",
            "The current-state figure for the required outcome {outcome} was elicited from people "
            "rather than measured, and the outcome sets a numeric target.",
            _PROCEED,
            "Measure the current state, or declare the outcome as directional or no-regression if "
            "it is not a numeric target.",
        ),
        "fixed-workflow-residual-contradiction": RulePhrases(
            "gap",
            "The dossier says a fixed sequence of steps is enough and also records the case "
            "{residual} that it cannot handle.",
            _PROCEED,
            "Remove or correct the case, or change the answer if the evidence supports it.",
        ),
        "hard-veto-status-unknown": RulePhrases(
            "gap",
            "Whether the absolute stop condition {condition} applies is not recorded.",
            _PROCEED,
            "Record whether the stop condition is in force, with evidence.",
        ),
        "mandatory-human-control-omitted": RulePhrases(
            "stop",
            "{candidate} would remove the person-required step {control}.",
            _ELIMINATED,
            "Keep the person-required step in the option, or consider an option that keeps it.",
        ),
        "mandatory-human-control-retained": RulePhrases(
            "condition",
            "{candidate} keeps the person-required step {control}.",
            "The option stays open with that step kept.",
            "No action is needed.",
        ),
        "non-discriminating-binding-set": RulePhrases(
            "gap",
            "The required outcomes and constraints do not separate the options: every option "
            "meets them, or the current way of working misses none of them.",
            _PROCEED,
            "Record a required outcome the current way of working misses, promote a recorded fact "
            "to a requirement, or declare that keeping the current way of working is intended.",
        ),
        "overlapping-veto-status-unknown": RulePhrases(
            "gap",
            "Whether the absolute stop condition {condition} applies to {candidate} is not "
            "recorded.",
            _UNDETERMINED,
            "Record whether the stop condition is in force, with evidence.",
        ),
        "problem-value-missing": RulePhrases(
            "gap",
            "The dossier does not say what problem is worth solving.",
            _PROCEED,
            "Record the required outcomes, the current state, the constraints, and the four value "
            "statements.",
        ),
        "required-candidate-role-missing": RulePhrases(
            "gap",
            "No option holds the role {role}.",
            _PROCEED,
            "Give the role to exactly one fitting option.",
        ),
        "required-comparison-missing": RulePhrases(
            "gap",
            "{candidate} is not compared with {comparator}.",
            _PROCEED,
            "Record the pairwise comparison with evidence.",
        ),
        "strongest-simpler-boundary-coverage-missing": RulePhrases(
            "gap",
            "The statement of the strongest simpler alternative leaves out {candidate}.",
            _PROCEED,
            "Consider every simpler represented option in that statement.",
        ),
        "strongest-simpler-boundary-incompatible": RulePhrases(
            "gap",
            "The statement of the strongest simpler alternative names {candidate}, which does not "
            "hold that role or is not simpler.",
            _PROCEED,
            "Name the option that holds the role and is simpler than the proposal.",
        ),
        "strongest-simpler-boundary-missing": RulePhrases(
            "gap",
            "The dossier does not say why {candidate} is the strongest simpler alternative to the "
            "proposal.",
            _PROCEED,
            "Record the statement with its scope, reasoning, considered options, and evidence.",
        ),
        "task-boundary-missing": RulePhrases(
            "gap",
            "The dossier does not bound the task: what it is, when it starts and ends, who acts, "
            "and which actions matter.",
            _PROCEED,
            "Record the task boundary.",
        ),
        "verdict-conditional": RulePhrases(
            "fit",
            "The evidence indicates {candidate}, subject to the conditions {conditions}.",
            "The indicated option holds once the named conditions are met.",
            "Meet the named conditions.",
        ),
        "verdict-insufficient-evidence": RulePhrases(
            "gap",
            "More evidence is needed before an option can be indicated.",
            "No option is indicated until the missing evidence is recorded.",
            "Record the missing evidence named in the gaps.",
        ),
        "verdict-no-permissible-candidate": RulePhrases(
            "stop",
            "Every represented option is ruled out by the required outcomes and constraints.",
            "No represented option can be indicated under the current requirements.",
            "Change the requirements or represent a different option.",
        ),
        "verdict-no-technology-change": RulePhrases(
            "fit",
            "The evidence indicates keeping the work with people or redesigning the process, with "
            "no new technology.",
            "No new technology is indicated.",
            "No action is needed.",
        ),
        "verdict-supported": RulePhrases(
            "fit",
            "The evidence indicates {candidate} as the least complex option that meets every "
            "requirement.",
            "The indicated option is supported by the current evidence.",
            "No action is needed.",
        ),
    }
)


def excluded_words_in(text: str) -> tuple[str, ...]:
    """Return the excluded words found in text, lowercased, in order of appearance."""
    return tuple(match.group(0).lower() for match in _EXCLUDED_PATTERN.finditer(text))


def _check_phrase(context: str, text: str) -> None:
    hits = excluded_words_in(text)
    if hits:
        raise VocabularyError(
            f"Vocabulary phrase for {context} contains excluded words {', '.join(hits)}; "
            "reword it in the neutral register."
        )
    if not text.strip():
        raise VocabularyError(f"Vocabulary phrase for {context} is empty.")


def validate_vocabulary() -> None:
    """Fail closed on any unmapped term or any phrase outside the neutral register."""
    mappings: tuple[tuple[Mapping[Any, str], tuple[Any, ...], str], ...] = (
        (FLAGS, tuple(RuleEffect), "finding effect"),
        (VERDICTS, tuple(ArchitectureVerdict), "verdict"),
        (EVIDENCE_STATES, tuple(EvidenceState), "verdict-confidence evidence state"),
        (OPTIONS, tuple(ControlClass), "control class"),
        (EVIDENCE_KINDS, tuple(EvidenceKind), "evidence-entry kind"),
        (QUESTIONS, tuple(DecisionArea), "decision area"),
    )
    for mapping, values, label in mappings:
        for value in values:
            if value not in mapping:
                raise VocabularyError(f"No reader-facing phrase for {label} {value.value!r}.")
            _check_phrase(f"{label} {value.value!r}", mapping[value])
    for flag in FLAGS.values():
        if flag not in FLAG_MEANINGS:
            raise VocabularyError(f"No meaning for flag {flag!r}.")
        _check_phrase(f"flag {flag!r}", FLAG_MEANINGS[flag])
    catalog = {rule.id: rule for rule in list_rules()}
    for rule_id in catalog:
        if rule_id not in RULES:
            raise VocabularyError(f"No reader-facing phrases for rule {rule_id!r}.")
    for rule_id, phrases in RULES.items():
        if rule_id not in catalog:
            raise VocabularyError(f"Vocabulary names unknown rule {rule_id!r}.")
        expected_flag = FLAGS[catalog[rule_id].effect]
        if phrases.flag != expected_flag:
            raise VocabularyError(
                f"Rule {rule_id!r} carries flag {phrases.flag!r} but its effect renders as "
                f"{expected_flag!r}."
            )
        for name in ("message", "consequence", "remediation"):
            _check_phrase(f"rule {rule_id!r} {name}", getattr(phrases, name))
    for label, mapping in (
        ("question", QUESTION_FIELDS),
        ("dimension", DIMENSIONS),
        ("role", ROLES),
        ("test result", TEST_RESULTS),
        ("comparison result", COMPARISON_RESULTS),
        ("answer", ANSWERS),
        ("stop-condition state", STOP_CONDITION_STATES),
        ("condition state", CONDITION_STATES),
        ("author", AUTHORS),
        ("target kind", TARGET_KINDS),
        ("disposition", DISPOSITIONS),
    ):
        for key, text in mapping.items():
            _check_phrase(f"{label} {key!r}", text)
    for context, text in (
        ("result name", RESULT_NAME),
        ("indicated option", INDICATED_OPTION),
        ("decision owner statement", DECISION_OWNER_STATEMENT),
    ):
        _check_phrase(context, text)


def term(mapping: Mapping[str, str], key: str, label: str) -> str:
    """Return the reader-facing phrase for one structured token, failing closed."""
    try:
        return mapping[key]
    except KeyError:
        raise VocabularyError(
            f"No reader-facing phrase for {label} {key!r}; add it to the vocabulary before "
            "rendering."
        ) from None


def rule_phrases(rule_id: str) -> RulePhrases:
    """Return the reader-facing phrases for one packaged rule, failing closed."""
    try:
        return RULES[rule_id]
    except KeyError:
        raise VocabularyError(
            f"No reader-facing phrases for rule {rule_id!r}; add them to the vocabulary before "
            "rendering."
        ) from None


def phrase(term: object) -> str:
    """Return the reader-facing phrase for one enumerated internal term, failing closed."""
    mappings: tuple[Mapping[Any, str], ...] = (
        FLAGS,
        VERDICTS,
        EVIDENCE_STATES,
        OPTIONS,
        EVIDENCE_KINDS,
        QUESTIONS,
    )
    for mapping in mappings:
        if term in mapping:
            return mapping[term]
    raise VocabularyError(
        f"No reader-facing phrase for {term!r}; add it to the vocabulary before rendering."
    )


def vocabulary_payload() -> dict[str, object]:
    """Return the deterministic JSON-compatible vocabulary, validated first."""
    validate_vocabulary()
    return {
        "answers": dict(ANSWERS),
        "authors": dict(AUTHORS),
        "comparison_results": dict(COMPARISON_RESULTS),
        "condition_states": dict(CONDITION_STATES),
        "decision_owner_statement": DECISION_OWNER_STATEMENT,
        "dimensions": dict(DIMENSIONS),
        "dispositions": dict(DISPOSITIONS),
        "decision_questions": {area.value: QUESTIONS[area] for area in DecisionArea},
        "evidence_kinds": {kind.value: EVIDENCE_KINDS[kind] for kind in EvidenceKind},
        "evidence_states": {state.value: EVIDENCE_STATES[state] for state in EvidenceState},
        "excluded_words": list(EXCLUDED_WORDS),
        "flag_meanings": dict(FLAG_MEANINGS),
        "flags": {effect.value: FLAGS[effect] for effect in RuleEffect},
        "question_fields": dict(QUESTION_FIELDS),
        "roles": dict(ROLES),
        "stop_condition_states": dict(STOP_CONDITION_STATES),
        "target_kinds": dict(TARGET_KINDS),
        "test_results": dict(TEST_RESULTS),
        "indicated_option": INDICATED_OPTION,
        "options": {control_class.value: OPTIONS[control_class] for control_class in ControlClass},
        "result_name": RESULT_NAME,
        "rules": {
            rule_id: {
                "consequence": phrases.consequence,
                "flag": phrases.flag,
                "message": phrases.message,
                "remediation": phrases.remediation,
            }
            for rule_id, phrases in sorted(RULES.items())
        },
        "specification": VOCABULARY_SPECIFICATION,
        "verdicts": {verdict.value: VERDICTS[verdict] for verdict in ArchitectureVerdict},
        "version": VOCABULARY_VERSION,
    }
