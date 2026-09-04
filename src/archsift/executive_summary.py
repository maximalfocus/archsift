"""The executive summary: one record told in three parts for a stakeholder (FR-017).

The summary is built from the masked JSON form of a canonical record and is
rendered identically as HTML and as a PPTX deck, so the two formats cannot
state different facts about one record. It speaks only through the published
vocabulary (NFR-011): every internal term is named by its phrase, every authored
element by its authored name or description, and every finding through its
rule's message template. It carries no internal identifier and no traceability
appendix; the detailed report keeps the full trace.

The three parts, in fixed order:

1. **Summary** — the operational task, the result, what happens next, and who
   decides.
2. **Business analysis** — the affected volume, the material pain, the cost of
   an error, and the limiting factor, then a process view of the recorded task
   boundary: start and completion conditions, actors, the ordered actions, and
   which actions a person must perform or confirm.
3. **Result and reasoning** — the options considered with the flags each one
   carries and the framework rule that raised each, the absolute stop
   conditions and person-required steps that apply,
   and, where more evidence is needed, what is already determined and what
   specific information would settle the rest.

The three parts are followed by the reference page **How the result was
reached**: the decision framework card (FR-020) for the framework version the
summary was built with, rendered unchanged.

Nothing here selects, satisfies, or promotes anything: the parts restate facts
the record already contains, and the decision rests with the accountable owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from archsift.canonical import JsonObject, JsonValue
from archsift.decision import ArchitectureVerdict
from archsift.framework import FrameworkCard, build_framework_card
from archsift.narrative import (
    Names,
    ResolvedFinding,
    finding_candidate_id,
    resolve_finding,
)
from archsift.record_view import (
    ReportRecordError,
    masked_record_view,
    require_object,
    require_text,
)
from archsift.rules import RuleEffect
from archsift.validation import ControlClass, EvidenceKind
from archsift.vocabulary import (
    DECISION_OWNER_STATEMENT,
    DISPOSITIONS,
    FLAG_MEANINGS,
    phrase,
    term,
)

EXECUTIVE_SUMMARY_VERSION: Final = 2

#: The three parts of every executive summary, in the order they are told.
PART_TITLES: Final[tuple[str, str, str]] = ("Summary", "Business analysis", "Result and reasoning")

_NOT_RECORDED: Final = "Not yet recorded."
_WHOLE: Final = "The options as a whole"


@dataclass(frozen=True, slots=True)
class SummaryStatement:
    """One labelled statement in a part.

    ``label`` is fixed vocabulary text. ``text`` is composed from fixed
    vocabulary text and verbatim masked record content, and from nothing else.
    """

    label: str
    text: str


@dataclass(frozen=True, slots=True)
class SummaryPart:
    """One of the three narrative parts."""

    title: str
    statements: tuple[SummaryStatement, ...]


@dataclass(frozen=True, slots=True)
class ExecutiveSummary:
    """One record's complete executive summary, ready to render in any format.

    A rendering is addressed by ``record_content_identity`` together with
    ``vocabulary_version`` and ``framework_version``: a wording change in the
    vocabulary or the framework card produces a distinct rendering while the
    record stays untouched.
    """

    record_content_identity: str
    vocabulary_version: str
    framework_version: str
    case_title: str
    language: str
    parts: tuple[SummaryPart, SummaryPart, SummaryPart]
    #: The reference page "How the result was reached": the framework card, unchanged.
    card: FrameworkCard


def _text(value: JsonValue, name: str) -> str:
    return require_text(value, name)


def _objects(value: JsonValue, name: str) -> tuple[JsonObject, ...]:
    if type(value) is not list:
        raise ReportRecordError(f"Decision record {name} is not a JSON array.")
    return tuple(require_object(item, f"{name}[]") for item in value)


def _strings(value: JsonValue, name: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise ReportRecordError(f"Decision record {name} is not a JSON array.")
    return tuple(_text(item, name) for item in value)


def _sentence(text: str) -> str:
    """Return ``text`` as a sentence: capitalised and closed with a full stop."""
    if not text:
        return text
    closed = text if text[-1] in ".!?" else text + "."
    return closed[0].upper() + closed[1:]


def _clause(text: str) -> str:
    """Return authored text as a clause inside a longer sentence: no closing full stop."""
    return text[:-1] if text.endswith(".") else text


def _join(items: list[str]) -> str:
    return "; ".join(_clause(item) for item in items)


# ---------------------------------------------------------------------------
# Shared readings of the record


def _task(dossier: JsonObject) -> JsonObject | None:
    task = dossier["task"]
    return None if task is None else require_object(task, "$.dossier.task")


def _comparison(dossier: JsonObject) -> JsonObject | None:
    comparison = dossier["candidate_comparison"]
    return (
        None if comparison is None else require_object(comparison, "$.dossier.candidate_comparison")
    )


def _autonomy(dossier: JsonObject) -> JsonObject | None:
    autonomy = dossier["autonomy_permission"]
    return None if autonomy is None else require_object(autonomy, "$.dossier.autonomy_permission")


def _active_vetoes(autonomy: JsonObject | None) -> tuple[JsonObject, ...]:
    if autonomy is None:
        return ()
    return tuple(
        veto
        for veto in _objects(autonomy["hard_vetoes"], "$.dossier.autonomy_permission.hard_vetoes")
        if veto["status"] == "active"
    )


def _controls(autonomy: JsonObject | None) -> tuple[JsonObject, ...]:
    if autonomy is None:
        return ()
    return _objects(
        autonomy["mandatory_human_controls"],
        "$.dossier.autonomy_permission.mandatory_human_controls",
    )


def _evidence(dossier: JsonObject) -> tuple[JsonObject, ...]:
    """Return the evidence ledger, refusing an entry kind the vocabulary cannot name."""
    entries = _objects(dossier["evidence"], "$.dossier.evidence")
    kinds = {item.value for item in EvidenceKind}
    for entry in entries:
        kind = _text(entry["kind"], "$.dossier.evidence[].kind")
        if kind not in kinds:
            raise ReportRecordError(f"Decision record evidence kind {kind} is unsupported.")
    return entries


# ---------------------------------------------------------------------------
# Part 1 — Summary


def _result_text(assessment: JsonObject, names: Names) -> str:
    verdict = ArchitectureVerdict(_text(assessment["verdict"], "$.assessment.verdict"))
    text = _sentence(phrase(verdict))
    recommended = assessment.get("recommended_class")
    if type(recommended) is str:
        option = phrase(ControlClass(recommended))
        surviving = _strings(
            assessment["surviving_candidate_ids"], "$.assessment.surviving_candidate_ids"
        )
        named = [names.candidate(x) for x in surviving if x in names.candidates]
        text += f" The indicated option is {option}"
        text += f": {_join(named)}." if named else "."
    return text


def _next_text(assessment: JsonObject) -> str:
    verdict = ArchitectureVerdict(_text(assessment["verdict"], "$.assessment.verdict"))
    unmet = _objects(assessment["unmet_conditions"], "$.assessment.unmet_conditions")
    if unmet:
        conditions = " ".join(
            f"{_sentence(_text(c['statement'], '$.unmet_conditions[].statement'))} Settled by: "
            f"{_sentence(_text(c['resolved_by'], '$.unmet_conditions[].resolved_by'))}"
            for c in unmet
        )
        return f"Before the indicated option can be relied on: {conditions}"
    if verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE:
        return (
            "Record the information listed under Result and reasoning, then run the review "
            "again; the result stays open until then."
        )
    if assessment.get("recommended_class") is None:
        return (
            "No option considered can be indicated under the rules; any further option would "
            "need its own recorded evidence."
        )
    return (
        "The accountable owner decides whether to proceed with the indicated option; the "
        "person-required steps and absolute stop conditions listed under Result and "
        "reasoning stay in place."
    )


def _summary_part(dossier: JsonObject, assessment: JsonObject, names: Names) -> SummaryPart:
    task = _task(dossier)
    statements = [
        SummaryStatement(
            "The task",
            _sentence(_text(task["operation"], "$.dossier.task.operation"))
            if task is not None
            else "The task is not yet recorded.",
        ),
        SummaryStatement("The result", _result_text(assessment, names)),
        SummaryStatement("What happens next", _next_text(assessment)),
    ]
    decides = DECISION_OWNER_STATEMENT
    if task is not None:
        owner = _text(task["accountable_owner"], "$.dossier.task.accountable_owner")
        decides += f" The accountable owner is {owner}."
    statements.append(SummaryStatement("Who decides", decides))
    return SummaryPart(PART_TITLES[0], tuple(statements))


# ---------------------------------------------------------------------------
# Part 2 — Business analysis


_BUSINESS_STATEMENTS: Final[tuple[tuple[str, str], ...]] = (
    ("affected_volume", "How much work is affected"),
    ("material_pain", "What hurts today"),
    ("error_cost", "What an error costs"),
    ("technology_limitation", "Why technology may be the limit"),
)


def _person_required(
    action_id: str, vetoes: tuple[JsonObject, ...], controls: tuple[JsonObject, ...]
) -> tuple[list[str], list[str]]:
    """Return the authored steps and stop conditions that bind one action to a person."""
    steps: list[str] = []
    for control in controls:
        if action_id in _strings(control["action_ids"], "$.mandatory_human_controls[].action_ids"):
            steps.append(
                f"{_clause(_text(control['description'], '$.controls[].description'))} "
                f"({_text(control['responsible_role'], '$.controls[].responsible_role')})"
            )
    stops = [
        _text(veto["condition"], "$.hard_vetoes[].condition")
        for veto in vetoes
        if action_id in _strings(veto["action_ids"], "$.hard_vetoes[].action_ids")
    ]
    return steps, stops


def _business_part(dossier: JsonObject) -> SummaryPart:
    statements: list[SummaryStatement] = []
    problem = dossier["problem_value"]
    if problem is None:
        statements.append(SummaryStatement("The business case", _NOT_RECORDED))
    else:
        problem_object = require_object(problem, "$.dossier.problem_value")
        for key, label in _BUSINESS_STATEMENTS:
            statement = require_object(problem_object[key], f"$.dossier.problem_value.{key}")
            statements.append(
                SummaryStatement(
                    label,
                    _sentence(_text(statement["statement"], f"$.problem_value.{key}.statement")),
                )
            )
    task = _task(dossier)
    if task is None:
        statements.append(SummaryStatement("How the work runs today", _NOT_RECORDED))
        return SummaryPart(PART_TITLES[1], tuple(statements))
    starts = _sentence(_text(task["starts_when"], "$.dossier.task.starts_when"))
    completes = _sentence(_text(task["completes_when"], "$.dossier.task.completes_when"))
    statements.append(
        SummaryStatement(
            "How the work runs today",
            f"It starts when: {starts} It is complete when: {completes}",
        )
    )
    actors = _strings(task["actors"], "$.dossier.task.actors")
    statements.append(
        SummaryStatement(
            "Who takes part", _sentence(", ".join(actors)) if actors else "None recorded."
        )
    )
    statements.append(
        SummaryStatement(
            "Accountable owner",
            _sentence(_text(task["accountable_owner"], "$.dossier.task.accountable_owner")),
        )
    )
    autonomy = _autonomy(dossier)
    vetoes, controls = _active_vetoes(autonomy), _controls(autonomy)
    for number, action in enumerate(_objects(task["actions"], "$.dossier.task.actions"), start=1):
        text = _sentence(_text(action["description"], "$.dossier.task.actions[].description"))
        text += (
            " This step is consequential."
            if action["consequential"] is True
            else " This step is not consequential."
        )
        steps, stops = _person_required(
            _text(action["id"], "$.dossier.task.actions[].id"), vetoes, controls
        )
        if steps:
            text += f" A person must perform or confirm this step: {_join(steps)}."
        if stops:
            text += f" It stops if: {_join(stops)}."
        if not steps and not stops:
            text += " No person-required step or absolute stop condition binds this step."
        statements.append(SummaryStatement(f"Step {number}", text))
    return SummaryPart(PART_TITLES[1], tuple(statements))


# ---------------------------------------------------------------------------
# Part 3 — Result and reasoning


def _findings_by_option(
    record: JsonObject, assessment: JsonObject, names: Names
) -> dict[str | None, list[ResolvedFinding]]:
    """Group every decisive finding by the option it is about, in record order."""
    grouped: dict[str | None, list[ResolvedFinding]] = {}
    prerequisites = require_object(
        assessment["prerequisite_evaluation"], "$.assessment.prerequisite_evaluation"
    )
    elimination = require_object(
        assessment["ordered_elimination_evaluation"], "$.assessment.ordered_elimination_evaluation"
    )
    for source, findings in (
        ("prerequisite", prerequisites["findings"]),
        ("decision", elimination["findings"]),
    ):
        for finding in _objects(findings, f"$.assessment.{source} findings"):
            if finding["effect"] == RuleEffect.NON_DECISIVE.value:
                continue
            option = finding_candidate_id(names, finding, source=source)
            resolved = resolve_finding(record, names, finding, source=source)
            findings_for_option = grouped.setdefault(option, [])
            # One rule can reach the same option twice (once as a prerequisite
            # finding, once as a decision finding); the reader is told once.
            if resolved not in findings_for_option:
                findings_for_option.append(resolved)
    return grouped


def _dispositions(assessment: JsonObject) -> dict[str, str]:
    elimination = require_object(
        assessment["ordered_elimination_evaluation"], "$.assessment.ordered_elimination_evaluation"
    )
    return {
        _text(item["candidate_id"], "$.candidates[].candidate_id"): term(
            DISPOSITIONS, _text(item["disposition"], "$.candidates[].disposition"), "disposition"
        )
        for item in _objects(
            elimination["candidates"], "$.ordered_elimination_evaluation.candidates"
        )
    }


def _flag_text(findings: list[ResolvedFinding]) -> str:
    """State each flag with the framework rule that raised it (FR-017, FR-020)."""
    return " ".join(
        f"{finding.flag.capitalize()} flag (framework rule {finding.framework_rule}): "
        f"{finding.message} {finding.consequence}"
        for finding in findings
    )


def _options_statements(
    record: JsonObject, dossier: JsonObject, assessment: JsonObject, names: Names
) -> list[SummaryStatement]:
    comparison = _comparison(dossier)
    grouped = _findings_by_option(record, assessment, names)
    statements: list[SummaryStatement] = []
    if comparison is None:
        statements.append(SummaryStatement("Options considered", "No options are recorded yet."))
    else:
        dispositions = _dispositions(assessment)
        for candidate in _objects(
            comparison["candidates"], "$.dossier.candidate_comparison.candidates"
        ):
            identifier = _text(candidate["id"], "$.candidates[].id")
            name = _text(candidate["name"], "$.candidates[].name")
            kind = phrase(ControlClass(_text(candidate["control_class"], "$.candidates[].class")))
            description = _text(candidate["description"], "$.candidates[].description")
            text = f"{name}. {_sentence(description)}"
            text += f" Kind: {kind}."
            standing = dispositions.get(identifier)
            if standing is not None:
                text += f" Standing: {standing}."
            findings = grouped.pop(identifier, [])
            text += f" {_flag_text(findings)}" if findings else " No flag is raised on this option."
            statements.append(SummaryStatement("Option", text))
    whole = grouped.pop(None, [])
    for leftovers in grouped.values():
        whole.extend(leftovers)
    if whole:
        statements.append(SummaryStatement(_WHOLE, _flag_text(whole)))
    if comparison is not None:
        statements.extend(_comparison_decisions(comparison, names))
    return statements


def _comparison_decisions(comparison: JsonObject, names: Names) -> list[SummaryStatement]:
    """State the authored comparison decisions: the simplest strong option, a kept baseline."""
    statements: list[SummaryStatement] = []
    boundary = comparison.get("strongest_simpler_boundary")
    if boundary is not None:
        strongest = require_object(boundary, "$.candidate_comparison.strongest_simpler_boundary")
        identifier = _text(strongest["strongest_candidate_id"], "$.boundary.strongest_candidate_id")
        name = names.candidate(identifier) if identifier in names.candidates else identifier
        statements.append(
            SummaryStatement(
                "Strongest simpler alternative",
                f"{name}. {_sentence(_text(strongest['rationale'], '$.boundary.rationale'))}",
            )
        )
    retention = comparison.get("baseline_retention")
    if retention is not None:
        declared = require_object(retention, "$.candidate_comparison.baseline_retention")
        declared_by = _text(declared["declared_by"], "$.baseline_retention.declared_by")
        rationale = _text(declared["rationale"], "$.baseline_retention.rationale")
        statements.append(
            SummaryStatement(
                "Keeping the current way of working is intended",
                f"Declared by {declared_by}. {_sentence(rationale)}",
            )
        )
    return statements


def _control_statements(dossier: JsonObject) -> list[SummaryStatement]:
    autonomy = _autonomy(dossier)
    if autonomy is None:
        return [SummaryStatement("Stop conditions and person-required steps", _NOT_RECORDED)]
    statements = [
        SummaryStatement(
            "Absolute stop condition",
            f"{_sentence(_text(veto['condition'], '$.hard_vetoes[].condition'))} Then: "
            f"{_sentence(_text(veto['consequence'], '$.hard_vetoes[].consequence'))}",
        )
        for veto in _active_vetoes(autonomy)
    ]
    statements.extend(
        SummaryStatement(
            "Person-required step",
            f"{_sentence(_text(control['description'], '$.controls[].description'))} When: "
            f"{_sentence(_text(control['control_point'], '$.controls[].control_point'))} Who: "
            f"{_sentence(_text(control['responsible_role'], '$.controls[].responsible_role'))}",
        )
        for control in _controls(autonomy)
    )
    if not statements:
        statements.append(
            SummaryStatement("Stop conditions and person-required steps", "None are recorded.")
        )
    return statements


def _human_decision_statement(record: JsonObject) -> SummaryStatement | None:
    scope = record.get("abstention_scope")
    if scope is None:
        return None
    retained = require_object(scope, "$.abstention_scope")["human_decision_retained"]
    if retained is True:
        text = (
            "Human decision-making is kept by every option; the remaining choice is whether to "
            "assist at all."
        )
    elif retained is False:
        text = (
            "At least one option would act on a consequential step without a person-required "
            "step, or a consequential step has no recorded person-required step; the hand-over "
            "question is still open."
        )
    else:
        text = "No person-required steps or absolute stop conditions are recorded."
    return SummaryStatement("Human decision-making", text)


def _determined_statements(record: JsonObject, assessment: JsonObject) -> list[SummaryStatement]:
    """State what the rules have already determined while the result stays open."""
    elimination = require_object(
        assessment["ordered_elimination_evaluation"], "$.assessment.ordered_elimination_evaluation"
    )
    classes = _objects(
        elimination["control_classes"], "$.ordered_elimination_evaluation.control_classes"
    )
    by_standing: dict[str, list[str]] = {}
    for item in classes:
        standing = term(
            DISPOSITIONS,
            _text(item["disposition"], "$.control_classes[].disposition"),
            "disposition",
        )
        option = phrase(ControlClass(_text(item["control_class"], "$.control_classes[].class")))
        by_standing.setdefault(standing, []).append(option)
    text = (
        " ".join(
            _sentence(f"{standing}: {_join(options)}") for standing, options in by_standing.items()
        )
        if by_standing
        else "Nothing is determined yet."
    )
    statements = [SummaryStatement("Already determined", text)]
    human = _human_decision_statement(record)
    if human is not None:
        statements.append(human)
    return statements


def _settling_statements(
    record: JsonObject, dossier: JsonObject, names: Names, *, open_result: bool
) -> list[SummaryStatement]:
    """State the specific information that would settle, or later change, the result.

    While the result is open, the statements say what would settle the rest.
    Once a result is reached, a decision-bearing entry still missing is what
    would change it, and is told under that name instead.
    """
    needed: list[str] = []
    for gap in _objects(record["unresolved_gaps"], "$.unresolved_gaps"):
        if gap["effect"] == RuleEffect.NON_DECISIVE.value:
            continue
        resolved = resolve_finding(
            record, names, gap, source=_text(gap["source"], "$.unresolved_gaps[].source")
        )
        item = f"{resolved.message} {resolved.remediation}"
        if item not in needed:
            needed.append(item)
    links = require_object(record["evidence_links"], "$.evidence_links")
    for entry in _evidence(dossier):
        if entry["kind"] != EvidenceKind.MISSING.value:
            continue
        identifier = _text(entry["id"], "$.dossier.evidence[].id")
        link = links.get(identifier)
        # Records before schema 3 carry no citation marker; every entry bears then.
        bearing = (
            require_object(link, f"$.evidence_links.{identifier}").get("decision_bearing", True)
            if link is not None
            else True
        )
        if bearing is not True:
            continue
        item = (
            f"{_sentence(_text(entry['claim'], '$.dossier.evidence[].claim'))} Settled by: "
            f"{_sentence(_text(entry['resolved_by'], '$.dossier.evidence[].resolved_by'))}"
        )
        if item not in needed:
            needed.append(item)
    label = "What would settle the rest" if open_result else "What would change the result"
    if not needed:
        return [SummaryStatement(label, "Nothing further is recorded.")] if open_result else []
    return [SummaryStatement(label, item) for item in needed]


def _reasoning_part(
    record: JsonObject, dossier: JsonObject, assessment: JsonObject, names: Names
) -> SummaryPart:
    statements = _options_statements(record, dossier, assessment, names)
    statements.extend(_control_statements(dossier))
    verdict = ArchitectureVerdict(_text(assessment["verdict"], "$.assessment.verdict"))
    unmet = _objects(assessment["unmet_conditions"], "$.assessment.unmet_conditions")
    open_result = verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE or bool(unmet)
    if open_result:
        statements.extend(_determined_statements(record, assessment))
    statements.extend(_settling_statements(record, dossier, names, open_result=open_result))
    legend = " ".join(
        f"{flag.capitalize()} flag: {meaning}" for flag, meaning in FLAG_MEANINGS.items()
    )
    statements.append(SummaryStatement("How to read the flags", legend))
    return SummaryPart(PART_TITLES[2], tuple(statements))


# ---------------------------------------------------------------------------


def build_executive_summary(record: JsonObject) -> ExecutiveSummary:
    """Return one deterministic three-part executive summary of a loaded canonical record."""
    view = masked_record_view(record)
    masked, dossier, assessment = view.record, view.dossier, view.assessment
    case = require_object(dossier["case"], "$.dossier.case")
    # The evidence ledger is read for its shape before any part is told, so a
    # malformed record fails closed rather than producing a partial summary.
    _evidence(dossier)
    names = Names(dossier)
    card = build_framework_card()
    return ExecutiveSummary(
        record_content_identity=_text(
            masked["record_content_identity"], "$.record_content_identity"
        ),
        vocabulary_version=card.vocabulary_version,
        framework_version=card.framework_version,
        case_title=_text(case["title"], "$.dossier.case.title"),
        language=view.language,
        parts=(
            _summary_part(dossier, assessment, names),
            _business_part(dossier),
            _reasoning_part(masked, dossier, assessment, names),
        ),
        card=card,
    )
