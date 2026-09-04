"""Plain-language narrative of a decision record (NFR-011).

The narrative is built from the masked JSON form of a record and speaks only
through the published vocabulary: every internal term is rendered by its
phrase, every authored element by its authored name or description, and every
finding through its rule's message template, consequence, and remediation.
It carries no identifier. The full internal trace stays in the traceability
appendix the renderers emit after it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from archsift.canonical import JsonObject, JsonValue
from archsift.decision import ArchitectureVerdict, EvidenceState
from archsift.rules import RuleEffect
from archsift.validation import ControlClass, DecisionArea, EvidenceKind
from archsift.vocabulary import (
    ANSWERS,
    AUTHORS,
    COMPARISON_RESULTS,
    DECISION_OWNER_STATEMENT,
    DIMENSIONS,
    DISPOSITIONS,
    FLAG_MEANINGS,
    INDICATED_OPTION,
    OPTIONS,
    QUESTION_FIELDS,
    QUESTIONS,
    ROLES,
    STOP_CONDITION_STATES,
    TARGET_KINDS,
    TEST_RESULTS,
    VOCABULARY_VERSION,
    RulePhrases,
    VocabularyError,
    framework_rule_number,
    phrase,
    rule_phrases,
    term,
)

_PLACEHOLDER: Final = re.compile(r"\{([a-z_]+)\}")
_INDEXED: Final = re.compile(r"^([a-z_]+)\[(\d+)\]$")


@dataclass(frozen=True, slots=True)
class NarrativeItem:
    """One labelled statement in a narrative section; the label is fixed vocabulary text."""

    label: str
    text: str


@dataclass(frozen=True, slots=True)
class NarrativeSection:
    """One reader-facing section named by fixed vocabulary text."""

    title: str
    items: tuple[NarrativeItem, ...]


@dataclass(frozen=True, slots=True)
class Narrative:
    """The complete plain-language narrative of one record."""

    vocabulary_version: str
    sections: tuple[NarrativeSection, ...]


def _obj(value: JsonValue, where: str) -> JsonObject:
    if type(value) is not dict:
        raise VocabularyError(f"Narrative expected an object at {where}.")
    return value


def _lst(value: JsonValue, where: str) -> list[JsonValue]:
    if type(value) is not list:
        raise VocabularyError(f"Narrative expected a list at {where}.")
    return value


def _str(value: JsonValue, where: str) -> str:
    if type(value) is not str:
        raise VocabularyError(f"Narrative expected text at {where}.")
    return value


def _objs(value: JsonValue, where: str) -> list[JsonObject]:
    return [_obj(item, where) for item in _lst(value, where)]


def _yes_no(value: JsonValue) -> str:
    return "yes" if value is True else "no"


class Names:
    """Authored names for the elements a finding can cite, keyed as the record keys them."""

    def __init__(self, dossier: JsonObject) -> None:
        self.dossier = dossier
        self.candidates: dict[str, JsonObject] = {}
        self.outcomes: dict[str, JsonObject] = {}
        self.constraints: dict[str, JsonObject] = {}
        self.baselines: dict[str, JsonObject] = {}
        self.vetoes: dict[str, JsonObject] = {}
        self.controls: dict[str, JsonObject] = {}
        self.residuals: dict[str, JsonObject] = {}
        self.conditions: dict[str, JsonObject] = {}
        self.evidence: dict[str, JsonObject] = {}
        self.actions: dict[str, JsonObject] = {}
        comparison = dossier.get("candidate_comparison")
        if comparison is not None:
            for item in _objs(
                _obj(comparison, "$.candidate_comparison")["candidates"], "candidates"
            ):
                self.candidates[_str(item["id"], "candidate id")] = item
        problem = dossier.get("problem_value")
        if problem is not None:
            problem_object = _obj(problem, "$.problem_value")
            for item in _objs(problem_object["outcomes"], "outcomes"):
                self.outcomes[_str(item["id"], "outcome id")] = item
            for item in _objs(problem_object["constraints"], "constraints"):
                self.constraints[_str(item["id"], "constraint id")] = item
            for item in _objs(problem_object["baselines"], "baselines"):
                self.baselines[_str(item["id"], "baseline id")] = item
        autonomy = dossier.get("autonomy_permission")
        if autonomy is not None:
            autonomy_object = _obj(autonomy, "$.autonomy_permission")
            for item in _objs(autonomy_object["hard_vetoes"], "hard_vetoes"):
                self.vetoes[_str(item["id"], "veto id")] = item
            for item in _objs(autonomy_object["mandatory_human_controls"], "controls"):
                self.controls[_str(item["id"], "control id")] = item
        agency = dossier.get("agency_necessity")
        if agency is not None:
            for item in _objs(_obj(agency, "$.agency_necessity")["residual_cases"], "residuals"):
                self.residuals[_str(item["id"], "residual id")] = item
        for item in _objs(dossier["decision_conditions"], "decision_conditions"):
            self.conditions[_str(item["id"], "condition id")] = item
        for item in _objs(dossier["evidence"], "evidence"):
            self.evidence[_str(item["id"], "evidence id")] = item
        task = dossier.get("task")
        if task is not None:
            for item in _objs(_obj(task, "$.task")["actions"], "actions"):
                self.actions[_str(item["id"], "action id")] = item

    def candidate(self, identifier: str) -> str:
        return _str(self.candidates[identifier]["name"], "candidate name")

    def described(self, table: dict[str, JsonObject], identifier: str, key: str) -> str:
        return _str(table[identifier][key], f"{key} of {identifier}")


def _resolve_path(names: Names, path: str, values: dict[str, str]) -> None:
    """Fill placeholders from a diagnostic field path such as $.problem_value.outcomes[0]."""
    segments = path.removeprefix("$.").split(".")
    node: JsonValue = names.dossier
    candidate: JsonObject | None = None
    for segment in segments:
        match = _INDEXED.match(segment)
        key = match.group(1) if match else segment
        if type(node) is not dict or key not in node:
            break
        node = node[key]
        if match:
            index = int(match.group(2))
            items = _lst(node, path)
            if index >= len(items):
                break
            node = items[index]
            element = _obj(node, path)
            if key == "outcomes":
                values.setdefault("outcome", _str(element["description"], path))
            elif key == "constraints":
                values.setdefault("constraint", _str(element["description"], path))
            elif key == "candidates":
                candidate = element
                values.setdefault("candidate", _str(element["name"], path))
            elif key == "outcome_tests":
                values.setdefault(
                    "outcome",
                    names.described(
                        names.outcomes, _str(element["outcome_id"], path), "description"
                    ),
                )
                values.setdefault("criterion", values["outcome"])
            elif key == "constraint_tests":
                values.setdefault(
                    "constraint",
                    names.described(
                        names.constraints, _str(element["constraint_id"], path), "description"
                    ),
                )
                values.setdefault("criterion", values["constraint"])
            elif key == "hard_vetoes":
                values.setdefault("condition", _str(element["condition"], path))
            elif key == "mandatory_human_controls":
                values.setdefault("control", _str(element["description"], path))
            elif key == "residual_cases":
                values.setdefault("residual", _str(element["description"], path))
            elif key == "comparisons":
                values.setdefault(
                    "candidate", names.candidate(_str(element["subject_candidate_id"], path))
                )
                values.setdefault(
                    "comparator", names.candidate(_str(element["comparator_candidate_id"], path))
                )
            elif key == "decision_conditions":
                values.setdefault("conditions", _str(element["statement"], path))
        elif key in QUESTION_FIELDS:
            values.setdefault("question", QUESTION_FIELDS[key])
        elif key in DIMENSIONS and "dimensions" in segments:
            values.setdefault("dimension", DIMENSIONS[key])
        elif key == "strongest_simpler_boundary" and type(node) is dict:
            boundary = node
            strongest = boundary.get("strongest_candidate_id")
            if type(strongest) is str and strongest in names.candidates:
                values.setdefault("candidate", names.candidate(strongest))
    if candidate is not None:
        values.setdefault("candidate", _str(candidate["name"], path))


def _resolve_decision_finding(names: Names, finding: JsonObject, values: dict[str, str]) -> None:
    candidate_id = finding.get("candidate_id")
    if type(candidate_id) is str and candidate_id in names.candidates:
        values.setdefault("candidate", names.candidate(candidate_id))
    elif candidate_id is None:
        # A dossier-level finding speaks about the options as a whole.
        values.setdefault("candidate", "the options as a whole")
    criterion = finding.get("criterion_id")
    kind = finding.get("criterion_kind")
    if type(criterion) is not str:
        return
    if kind == "outcome" and criterion in names.outcomes:
        values.setdefault("outcome", names.described(names.outcomes, criterion, "description"))
        values.setdefault("criterion", values["outcome"])
    elif kind == "constraint" and criterion in names.constraints:
        values.setdefault(
            "constraint", names.described(names.constraints, criterion, "description")
        )
        values.setdefault("criterion", values["constraint"])
    elif kind == "hard-veto" and criterion in names.vetoes:
        values.setdefault("condition", names.described(names.vetoes, criterion, "condition"))
        values.setdefault("boundary", values["condition"])
    elif kind == "human-control" and criterion in names.controls:
        values.setdefault("control", names.described(names.controls, criterion, "description"))
        values.setdefault("boundary", values["control"])
    elif kind in {"agency-question", "derived-agency"}:
        if criterion in QUESTION_FIELDS:
            values.setdefault("question", QUESTION_FIELDS[criterion])
        else:
            values.setdefault("question", criterion.replace("_", " ").replace("-", " "))
    elif kind == "residual-case" and criterion in names.residuals:
        values.setdefault("residual", names.described(names.residuals, criterion, "description"))


def _resolve_verdict(record: JsonObject, names: Names, values: dict[str, str]) -> None:
    assessment = _obj(record["assessment"], "$.assessment")
    recommended = assessment.get("recommended_class")
    if type(recommended) is str:
        values.setdefault("candidate", term(_option_phrases(), recommended, "control class"))
    unmet = _objs(assessment["unmet_conditions"], "unmet_conditions")
    if unmet:
        values.setdefault(
            "conditions",
            "; ".join(_str(item["statement"], "condition statement") for item in unmet),
        )


def _option_phrases() -> dict[str, str]:
    return {control_class.value: OPTIONS[control_class] for control_class in ControlClass}


@dataclass(frozen=True, slots=True)
class ResolvedFinding:
    """One finding rendered through its rule's vocabulary entry, placeholders resolved."""

    flag: str
    message: str
    consequence: str
    remediation: str
    #: The framework rule (FR-020) that raised the flag; a reader-facing number.
    framework_rule: int


def resolve_finding(
    record: JsonObject, names: Names, finding: JsonObject, *, source: str
) -> ResolvedFinding:
    """Render one finding's phrases with every placeholder resolved to an authored element.

    ``source`` is ``"prerequisite"`` for a finding that cites a field path and
    ``"decision"`` for one that cites a candidate and criterion. A rule without
    phrases, or a placeholder this finding does not resolve, fails closed.
    """
    rule_id = _str(finding["rule_id"], "finding rule_id")
    phrases: RulePhrases = rule_phrases(rule_id)
    values: dict[str, str] = {}
    if source == "prerequisite":
        _resolve_path(names, _str(finding["field"], "finding field"), values)
        counterpart = finding.get("counterpart")
        if type(counterpart) is str and counterpart.startswith("$."):
            _resolve_path(names, counterpart, values)
        if "role" not in values:
            role_match = re.search(
                r"required role '([a-z-]+)'", _str(finding["message"], "message")
            )
            if role_match:
                values["role"] = term(ROLES, role_match.group(1), "role")
    else:
        _resolve_decision_finding(names, finding, values)
    if rule_id.startswith("verdict-"):
        _resolve_verdict(record, names, values)
    text = phrases.message
    for placeholder in _PLACEHOLDER.findall(text):
        if placeholder not in values:
            raise VocabularyError(
                f"Rule {rule_id!r} message names {{{placeholder}}}, which this finding does not "
                "resolve to an authored element; extend the narrative resolver before rendering."
            )
        # An authored description is a sentence of its own; inside the template it
        # reads as a clause, so its closing full stop is dropped.
        text = text.replace("{" + placeholder + "}", values[placeholder].removesuffix("."))
    return ResolvedFinding(
        phrases.flag,
        text,
        phrases.consequence,
        phrases.remediation,
        framework_rule_number(rule_id),
    )


def finding_candidate_id(names: Names, finding: JsonObject, *, source: str) -> str | None:
    """Return the option a finding is about, or None when it is about the options as a whole."""
    if source != "prerequisite":
        candidate_id = finding.get("candidate_id")
        return candidate_id if type(candidate_id) is str else None
    for path in (finding.get("field"), finding.get("counterpart")):
        if type(path) is not str:
            continue
        match = re.search(r"\.candidates\[(\d+)\]", path)
        if match is None:
            continue
        index = int(match.group(1))
        identifiers = list(names.candidates)
        if index < len(identifiers):
            return identifiers[index]
    return None


def _render_finding(
    record: JsonObject, names: Names, finding: JsonObject, *, source: str
) -> NarrativeItem:
    resolved = resolve_finding(record, names, finding, source=source)
    return NarrativeItem(
        f"{resolved.flag} flag",
        f"{resolved.message} {resolved.consequence} What would settle it: {resolved.remediation}",
    )


def _result_section(record: JsonObject) -> NarrativeSection:
    assessment = _obj(record["assessment"], "$.assessment")
    verdict = ArchitectureVerdict(_str(assessment["verdict"], "verdict"))
    state = EvidenceState(_str(assessment["evidence_state"], "evidence_state"))
    items = [NarrativeItem("The result", phrase(verdict).capitalize() + ".")]
    recommended = assessment.get("recommended_class")
    if type(recommended) is str:
        items.append(
            NarrativeItem(
                INDICATED_OPTION.capitalize(),
                f"{phrase(ControlClass(recommended)).capitalize()}.",
            )
        )
    else:
        items.append(NarrativeItem(INDICATED_OPTION.capitalize(), "None yet."))
    items.append(NarrativeItem("Evidence state", phrase(state).capitalize() + "."))
    unmet = _objs(assessment["unmet_conditions"], "unmet_conditions")
    for condition in unmet:
        items.append(
            NarrativeItem(
                "Condition still to meet",
                f"{_str(condition['statement'], 'statement')} "
                f"Settled by: {_str(condition['resolved_by'], 'resolved_by')}",
            )
        )
    items.append(NarrativeItem("Who decides", DECISION_OWNER_STATEMENT))
    return NarrativeSection("The result", tuple(items))


def _scope_section(record: JsonObject, names: Names) -> NarrativeSection | None:
    scope = record.get("abstention_scope")
    if scope is None:
        return None
    scope_object = _obj(scope, "$.abstention_scope")
    items: list[NarrativeItem] = []
    for item in _objs(scope_object["eliminated_classes"], "eliminated_classes"):
        items.append(
            NarrativeItem(
                "Already ruled out",
                f"{phrase(ControlClass(_str(item['control_class'], 'class'))).capitalize()}.",
            )
        )
    for item in _objs(scope_object["undetermined_classes"], "undetermined_classes"):
        items.append(
            NarrativeItem(
                "Still open",
                f"{phrase(ControlClass(_str(item['control_class'], 'class'))).capitalize()}.",
            )
        )
    for control_class in _lst(scope_object["surviving_classes"], "surviving_classes"):
        items.append(
            NarrativeItem(
                "Still in play",
                f"{phrase(ControlClass(_str(control_class, 'class'))).capitalize()}.",
            )
        )
    retained = scope_object["human_decision_retained"]
    if retained is True:
        items.append(
            NarrativeItem(
                "Human decision-making",
                "Retained: no option proposes to replace it. The remaining choice is whether to "
                "assist at all.",
            )
        )
    elif retained is False:
        items.append(
            NarrativeItem(
                "Human decision-making",
                "At least one option proposes to act on a consequential action without a "
                "person-required step, or a consequential action has no evidenced step; the "
                "hand-over question is still open.",
            )
        )
    else:
        items.append(
            NarrativeItem(
                "Human decision-making", "No person-required steps or stop conditions are recorded."
            )
        )
    return NarrativeSection("What is already determined", tuple(items))


def _task_section(dossier: JsonObject) -> NarrativeSection:
    task = dossier.get("task")
    if task is None:
        return NarrativeSection("The task", (NarrativeItem("The task", "Not yet recorded."),))
    task_object = _obj(task, "$.task")
    items = [
        NarrativeItem("What is done", _str(task_object["operation"], "operation")),
        NarrativeItem("It starts when", _str(task_object["starts_when"], "starts_when")),
        NarrativeItem("It is complete when", _str(task_object["completes_when"], "completes_when")),
        NarrativeItem("Accountable owner", _str(task_object["accountable_owner"], "owner")),
        NarrativeItem(
            "Who takes part",
            ", ".join(_str(x, "actor") for x in _lst(task_object["actors"], "actors"))
            or "(none recorded)",
        ),
    ]
    for action in _objs(task_object["actions"], "actions"):
        weight = "consequential" if action["consequential"] is True else "not consequential"
        items.append(
            NarrativeItem(
                "Action",
                f"{_str(action['description'], 'action')} This action is {weight}. "
                f"{_str(action['approval_boundary'], 'approval_boundary')}",
            )
        )
    exclusions = [_str(x, "exclusion") for x in _lst(task_object["exclusions"], "exclusions")]
    if exclusions:
        items.append(NarrativeItem("Out of scope", "; ".join(exclusions)))
    return NarrativeSection("The task", tuple(items))


def _problem_section(dossier: JsonObject, names: Names) -> NarrativeSection:
    title = QUESTIONS[DecisionArea.PROBLEM_VALUE]
    problem = dossier.get("problem_value")
    if problem is None:
        return NarrativeSection(title, (NarrativeItem("Answer", "Not yet recorded."),))
    problem_object = _obj(problem, "$.problem_value")
    items: list[NarrativeItem] = []
    for outcome in _objs(problem_object["outcomes"], "outcomes"):
        binding = "required" if outcome["binding"] is True else "for comparison only"
        kind = outcome.get("target_kind")
        kind_text = (
            f" ({term(TARGET_KINDS, _str(kind, 'target_kind'), 'target kind')})"
            if type(kind) is str
            else ""
        )
        baseline_id = _str(outcome["baseline_id"], "baseline_id")
        baseline = names.baselines.get(baseline_id)
        today = (
            f" Today: {_str(baseline['value'], 'value')} ({_str(baseline['measure'], 'measure')})."
            if baseline is not None
            else " Today: not recorded."
        )
        items.append(
            NarrativeItem(
                f"Outcome, {binding}",
                f"{_str(outcome['description'], 'description')} Target: "
                f"{_str(outcome['target'], 'target')}{kind_text}, measured as "
                f"{_str(outcome['measure'], 'measure')}.{today}",
            )
        )
    for constraint in _objs(problem_object["constraints"], "constraints"):
        binding = "required" if constraint["binding"] is True else "for comparison only"
        items.append(
            NarrativeItem(
                f"Constraint, {binding}",
                f"{_str(constraint['description'], 'description')} Checked by: "
                f"{_str(constraint['test'], 'test')} Must show: "
                f"{_str(constraint['required_result'], 'required_result')}",
            )
        )
    for key, label in (
        ("affected_volume", "How much work is affected"),
        ("material_pain", "What hurts today"),
        ("error_cost", "What an error costs"),
        ("technology_limitation", "Why technology may be the limit"),
    ):
        statement = _obj(problem_object[key], key)
        items.append(NarrativeItem(label, _str(statement["statement"], key)))
    return NarrativeSection(title, tuple(items))


def _question_section(
    dossier: JsonObject, area: DecisionArea, key: str, fields: tuple[str, ...]
) -> NarrativeSection:
    title = QUESTIONS[area]
    section = dossier.get(key)
    if section is None:
        return NarrativeSection(title, (NarrativeItem("Answer", "Not yet recorded."),))
    section_object = _obj(section, f"$.{key}")
    items: list[NarrativeItem] = []
    for field in fields:
        question = _obj(section_object[field], field)
        answer = term(ANSWERS, _str(question["answer"], "answer"), "answer")
        items.append(
            NarrativeItem(
                term(QUESTION_FIELDS, field, "question"),
                f"{answer.capitalize()}. {_str(question['rationale'], 'rationale')}",
            )
        )
    if key == "agency_necessity":
        for residual in _objs(section_object["residual_cases"], "residual_cases"):
            items.append(
                NarrativeItem(
                    "A case a fixed sequence cannot handle",
                    f"{_str(residual['description'], 'description')} "
                    f"{_str(residual['fixed_workflow_failure'], 'failure')}",
                )
            )
    else:
        for veto in _objs(section_object["hard_vetoes"], "hard_vetoes"):
            state = term(
                STOP_CONDITION_STATES, _str(veto["status"], "status"), "stop-condition state"
            )
            items.append(
                NarrativeItem(
                    "Absolute stop condition",
                    f"{_str(veto['condition'], 'condition')} Then: "
                    f"{_str(veto['consequence'], 'consequence')} "
                    f"This condition is {state}.",
                )
            )
        for control in _objs(section_object["mandatory_human_controls"], "controls"):
            items.append(
                NarrativeItem(
                    "Person-required step",
                    f"{_str(control['description'], 'description')} When: "
                    f"{_str(control['control_point'], 'control_point')} Who: "
                    f"{_str(control['responsible_role'], 'responsible_role')}",
                )
            )
    return NarrativeSection(title, tuple(items))


def _options_section(dossier: JsonObject, names: Names) -> NarrativeSection:
    title = QUESTIONS[DecisionArea.COMPARATIVE_FIT]
    comparison = dossier.get("candidate_comparison")
    if comparison is None:
        return NarrativeSection(title, (NarrativeItem("Options", "Not yet recorded."),))
    comparison_object = _obj(comparison, "$.candidate_comparison")
    items: list[NarrativeItem] = []
    for candidate in _objs(comparison_object["candidates"], "candidates"):
        roles = [
            term(ROLES, _str(role, "role"), "role") for role in _lst(candidate["roles"], "roles")
        ]
        text = (
            f"{_str(candidate['description'], 'description')} Kind: "
            f"{phrase(ControlClass(_str(candidate['control_class'], 'class')))}."
        )
        if roles:
            text += " Role: " + "; ".join(roles) + "."
        for test in _objs(candidate["outcome_tests"], "outcome_tests"):
            outcome = names.described(
                names.outcomes, _str(test["outcome_id"], "outcome_id"), "description"
            )
            result = term(TEST_RESULTS, _str(test["result"], "result"), "test result")
            text += f" Against the outcome {outcome}: {result}."
        for test in _objs(candidate["constraint_tests"], "constraint_tests"):
            constraint = names.described(
                names.constraints, _str(test["constraint_id"], "constraint_id"), "description"
            )
            result = term(TEST_RESULTS, _str(test["result"], "result"), "test result")
            text += f" Against the constraint {constraint}: {result}."
        authority = candidate.get("authority")
        if type(authority) is dict:
            actions = [
                _str(names.actions[_str(x, "action")]["description"], "action")
                if _str(x, "action") in names.actions
                else _str(x, "action")
                for x in _lst(authority["action_ids"], "action_ids")
            ]
            kept = [
                names.described(names.controls, _str(x, "control"), "description")
                if _str(x, "control") in names.controls
                else _str(x, "control")
                for x in _lst(authority["retained_human_control_ids"], "retained")
            ]
            text += " It would carry out: " + "; ".join(actions) + "."
            if kept:
                text += " It keeps the person-required steps: " + "; ".join(kept) + "."
        items.append(NarrativeItem("Option", f"{_str(candidate['name'], 'name')}. {text}"))
    for pair in _objs(comparison_object["comparisons"], "comparisons"):
        subject = names.candidate(_str(pair["subject_candidate_id"], "subject"))
        comparator = names.candidate(_str(pair["comparator_candidate_id"], "comparator"))
        dimensions = _obj(pair["dimensions"], "dimensions")
        parts = []
        for field in DIMENSIONS:
            dimension = _obj(dimensions[field], field)
            parts.append(
                f"{DIMENSIONS[field]}: "
                + term(COMPARISON_RESULTS, _str(dimension["result"], "result"), "comparison result")
            )
        items.append(
            NarrativeItem(
                "Comparison", f"{subject} compared with {comparator}: " + "; ".join(parts) + "."
            )
        )
    boundary = comparison_object.get("strongest_simpler_boundary")
    if type(boundary) is dict:
        items.append(
            NarrativeItem(
                "Strongest simpler alternative",
                f"{names.candidate(_str(boundary['strongest_candidate_id'], 'strongest'))}. "
                f"{_str(boundary['rationale'], 'rationale')}",
            )
        )
    retention = comparison_object.get("baseline_retention")
    if type(retention) is dict:
        items.append(
            NarrativeItem(
                "Keeping the current way of working is intended",
                f"Declared by {_str(retention['declared_by'], 'declared_by')}. "
                f"{_str(retention['rationale'], 'rationale')}",
            )
        )
    return NarrativeSection(title, tuple(items))


def _findings_section(record: JsonObject, names: Names) -> NarrativeSection:
    assessment = _obj(record["assessment"], "$.assessment")
    items: list[NarrativeItem] = []
    prerequisites = _obj(assessment["prerequisite_evaluation"], "prerequisite_evaluation")
    for finding in _objs(prerequisites["findings"], "prerequisite findings"):
        if finding["effect"] == RuleEffect.NON_DECISIVE.value:
            continue
        items.append(_render_finding(record, names, finding, source="prerequisite"))
    elimination = _obj(
        assessment["ordered_elimination_evaluation"], "ordered_elimination_evaluation"
    )
    for finding in _objs(elimination["findings"], "decision findings"):
        items.append(_render_finding(record, names, finding, source="decision"))
    for result in _objs(elimination["control_classes"], "control_classes"):
        items.append(
            NarrativeItem(
                phrase(ControlClass(_str(result["control_class"], "class"))).capitalize(),
                term(
                    DISPOSITIONS, _str(result["disposition"], "disposition"), "disposition"
                ).capitalize()
                + ".",
            )
        )
    legend = "; ".join(f"{flag}: {meaning}" for flag, meaning in FLAG_MEANINGS.items())
    items.append(NarrativeItem("How to read the flags", legend))
    return NarrativeSection("What the rules found", tuple(items))


def _envelope_section(record: JsonObject, names: Names) -> NarrativeSection | None:
    envelope = record.get("assistance_envelope")
    if envelope is None:
        return None
    envelope_object = _obj(envelope, "$.assistance_envelope")
    items: list[NarrativeItem] = []
    for entry in _objs(envelope_object["entries"], "entries"):
        action_id = _str(entry["action_id"], "action_id")
        action = names.actions.get(action_id)
        label = _str(action["description"], "action") if action is not None else action_id
        parts = ["consequential" if entry["consequential"] is True else "not consequential"]
        parts.append(
            "a person must carry it out or confirm it"
            if entry["person_required"] is True
            else "no person-required step or stop condition binds it"
        )
        controls = [
            names.described(names.controls, _str(x, "control"), "description")
            for x in _lst(entry["mandatory_human_control_ids"], "controls")
            if _str(x, "control") in names.controls
        ]
        vetoes = [
            names.described(names.vetoes, _str(x, "veto"), "condition")
            for x in _lst(entry["active_hard_veto_ids"], "vetoes")
            if _str(x, "veto") in names.vetoes
        ]
        if controls:
            parts.append("person-required steps: " + "; ".join(controls))
        if vetoes:
            parts.append("absolute stop conditions: " + "; ".join(vetoes))
        authorities = _objs(entry["declared_authorities"], "declared_authorities")
        if not authorities:
            parts.append("no option proposes to carry it out")
        for authority in authorities:
            candidate = names.candidate(_str(authority["candidate_id"], "candidate"))
            statement = f"{candidate} would carry it out"
            kept = [
                names.described(names.controls, _str(x, "control"), "description")
                for x in _lst(authority["retained_human_control_ids"], "kept")
                if _str(x, "control") in names.controls
            ]
            dropped = [
                names.described(names.controls, _str(x, "control"), "description")
                for x in _lst(authority["omitted_human_control_ids"], "dropped")
                if _str(x, "control") in names.controls
            ]
            if kept:
                statement += ", keeping " + "; ".join(kept)
            if dropped:
                statement += ", without " + "; ".join(dropped)
            parts.append(statement)
        items.append(
            NarrativeItem(
                "Action",
                f"{label} " + ". ".join(part[0].upper() + part[1:] for part in parts) + ".",
            )
        )
    retained = envelope_object["human_decision_retained"] is True
    items.append(
        NarrativeItem(
            "Human decision-making",
            "Retained: no option proposes to replace it."
            if retained
            else "Not retained by every option: see the actions above.",
        )
    )
    return NarrativeSection("Who may act, action by action", tuple(items))


def _evidence_section(record: JsonObject, names: Names) -> NarrativeSection:
    links = _obj(record["evidence_links"], "$.evidence_links")
    items: list[NarrativeItem] = []
    for identifier, entry in sorted(names.evidence.items()):
        link = links.get(identifier)
        bearing = True
        if type(link) is dict:
            bearing = link.get("decision_bearing", True) is not False
        kind = phrase(EvidenceKind(_str(entry["kind"], "kind")))
        owner = _str(entry["owner"], "owner")
        text = f"{_str(entry['claim'], 'claim')} This is {kind}; recorded by {owner}."
        authorship = entry.get("authorship")
        if type(authorship) is dict:
            author = term(AUTHORS, _str(authorship["authored_by"], "author"), "author")
            confirmed = authorship["attested_by_accountable_person"] is True
            text += f" Authored by {author}" + (
                ", confirmed by an accountable person."
                if confirmed
                else ", not yet confirmed by an accountable person."
            )
        for key, lead in (
            ("resolved_by", "What would settle it: "),
            ("falsified_by", "What would disprove it: "),
            ("method", "Method: "),
        ):
            if key in entry:
                text += f" {lead}{_str(entry[key], key)}"
        elicitation = entry.get("elicitation")
        if type(elicitation) is dict:
            e = elicitation
            roles = ", ".join(_str(x, "role") for x in _lst(e["roles"], "roles"))
            text += f" Elicited from {roles}; covers {_str(e['coverage'], 'coverage')}."
        items.append(
            NarrativeItem(
                "Evidence the decision rests on" if bearing else "Recorded for context only", text
            )
        )
    if not items:
        items.append(NarrativeItem("Evidence", "None recorded."))
    return NarrativeSection("The evidence", tuple(items))


def _gaps_section(record: JsonObject, names: Names) -> NarrativeSection:
    items: list[NarrativeItem] = []
    for gap in _objs(record["unresolved_gaps"], "$.unresolved_gaps"):
        if gap["effect"] == RuleEffect.NON_DECISIVE.value:
            continue
        source = _str(gap["source"], "source")
        items.append(_render_finding(record, names, gap, source=source))
    for trigger in _objs(record["reassessment_triggers"], "$.reassessment_triggers"):
        kind = EvidenceKind(_str(trigger["kind"], "kind"))
        bearing = trigger.get("decision_bearing", True) is not False
        entry = names.evidence.get(_str(trigger["evidence_id"], "evidence_id"))
        claim = _str(entry["claim"], "claim") if entry is not None else "an entry"
        lead = "Would change the result" if bearing else "Recorded for context only"
        items.append(
            NarrativeItem(
                lead,
                f"{claim} ({phrase(kind)}): {_str(trigger['observation'], 'observation')}",
            )
        )
    if not items:
        items.append(NarrativeItem("Gaps", "None."))
    return NarrativeSection("What is still missing, and what would change the result", tuple(items))


def build_narrative(masked_record: JsonObject) -> Narrative:
    """Build the plain-language narrative of one masked canonical record."""
    dossier = _obj(masked_record["dossier"], "$.dossier")
    names = Names(dossier)
    sections: list[NarrativeSection] = [_result_section(masked_record)]
    scope = _scope_section(masked_record, names)
    if scope is not None:
        sections.append(scope)
    sections.extend(
        (
            _task_section(dossier),
            _problem_section(dossier, names),
            _question_section(
                dossier,
                DecisionArea.AGENCY_NECESSITY,
                "agency_necessity",
                tuple(list(QUESTION_FIELDS)[:8]),
            ),
            _question_section(
                dossier,
                DecisionArea.AUTONOMY_PERMISSION,
                "autonomy_permission",
                tuple(list(QUESTION_FIELDS)[8:]),
            ),
            _options_section(dossier, names),
            _findings_section(masked_record, names),
        )
    )
    envelope = _envelope_section(masked_record, names)
    if envelope is not None:
        sections.append(envelope)
    sections.extend((_evidence_section(masked_record, names), _gaps_section(masked_record, names)))
    return Narrative(vocabulary_version=VOCABULARY_VERSION, sections=tuple(sections))
