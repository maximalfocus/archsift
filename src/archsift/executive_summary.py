"""The deterministic executive summary of one canonical decision record.

FR-017: an executive summary states, for a stakeholder audience, the case
identity and task boundary in brief, the verdict or abstention with its rule
ID, the decision space, the active vetoes and mandatory human controls, the
evidence state with its material gaps, and the trade-offs that most affect the
verdict.

This module owns the summary itself; the HTML and PPTX renderers own only its
presentation. Both render the same :class:`ExecutiveSummary`, so the two
formats cannot state different facts about the same record.

**The summary introduces no fact the record does not contain.** Every value is
either verbatim record content or one of a small, closed set of derived values
— a count, or a fixed marker for an absent, empty, or abstaining outcome —
marked by :attr:`SummaryPoint.derived`. Labels and section titles are fixed
structural text and never carry record content.

Masking (NFR-009) is applied when the summary is built, so no rendering path
can present an unmasked authored value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from archsift.canonical import JsonObject, JsonValue
from archsift.record_view import (
    ABSENT,
    EMPTY,
    ReportRecordError,
    masked_record_view,
    recommendation,
    require_object,
    require_text,
)

EXECUTIVE_SUMMARY_VERSION: Final = 1

#: Values a point may carry that are computed rather than quoted. A derived
#: value is a decimal count or one of these fixed markers, and nothing else.
DERIVED_MARKERS: Final[frozenset[str]] = frozenset(
    {ABSENT, EMPTY, "(abstention)", "(no permissible candidate)"}
)
_DERIVED_COUNT: Final = re.compile(r"\d+(?: of \d+)?")

_EVIDENCE_KINDS: Final[tuple[str, ...]] = ("observed", "assumption", "estimate", "missing")
#: Pairwise comparison dimensions, in the order FR-008 declares them.
_DIMENSIONS: Final[tuple[str, ...]] = (
    "outcome_quality",
    "difficult_case_performance",
    "cost",
    "latency",
    "human_effort",
    "integration_burden",
    "security_exposure",
    "failure_impact",
    "operability",
    "evaluation_burden",
    "maintainability",
)
#: A comparison outcome that states a direction. `equivalent` and `unknown`
#: distinguish no candidate, so they cannot be a trade-off that affects the
#: verdict.
_DIRECTIONAL_RESULTS: Final[frozenset[str]] = frozenset({"better", "worse"})


@dataclass(frozen=True, slots=True)
class SummaryPoint:
    """One labelled statement in the summary.

    ``label`` is fixed structural text. Each entry of ``values`` is verbatim
    masked record content unless ``derived`` is set, in which case every entry
    is a count or a fixed marker.
    """

    label: str
    values: tuple[str, ...]
    derived: bool = False


@dataclass(frozen=True, slots=True)
class SummarySection:
    """One titled group of statements."""

    title: str
    points: tuple[SummaryPoint, ...]


@dataclass(frozen=True, slots=True)
class ExecutiveSummary:
    """One record's complete executive summary, ready to render in any format."""

    record_content_identity: str
    ruleset_version: str
    tool_version: str
    case_title: str
    language: str
    sections: tuple[SummarySection, ...]


def _text(value: JsonValue, name: str) -> str:
    return require_text(value, name)


def _optional_text(mapping: JsonObject | None, key: str, name: str) -> SummaryPoint | None:
    """Return one point for a field that a partial dossier may omit."""
    if mapping is None:
        return None
    return SummaryPoint(_LABELS[key], (_text(mapping[key], name),))


_LABELS: Final[dict[str, str]] = {
    "operation": "Operation",
    "starts_when": "Starts When",
    "completes_when": "Completes When",
    "accountable_owner": "Accountable Owner",
}


def _list_of_objects(value: JsonValue, name: str) -> tuple[JsonObject, ...]:
    if type(value) is not list:
        raise ReportRecordError(f"Decision record {name} is not a JSON array.")
    return tuple(require_object(item, f"{name}[]") for item in value)


def _strings(value: JsonValue, name: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise ReportRecordError(f"Decision record {name} is not a JSON array.")
    return tuple(_text(item, name) for item in value)


def _case_section(dossier: JsonObject) -> SummarySection:
    case = require_object(dossier["case"], "$.dossier.case")
    points = [
        SummaryPoint("Case ID", (_text(case["id"], "$.dossier.case.id"),)),
        SummaryPoint("Case", (_text(case["title"], "$.dossier.case.title"),)),
        SummaryPoint("Language", (_text(dossier["language"], "$.dossier.language"),)),
    ]
    task = dossier["task"]
    if task is None:
        points.append(SummaryPoint("Task Boundary", (ABSENT,), derived=True))
        return SummarySection("Case and Task Boundary", tuple(points))
    boundary = require_object(task, "$.dossier.task")
    for key in ("operation", "starts_when", "completes_when", "accountable_owner"):
        point = _optional_text(boundary, key, f"$.dossier.task.{key}")
        if point is not None:
            points.append(point)
    actions = _list_of_objects(boundary["actions"], "$.dossier.task.actions")
    consequential = sum(1 for action in actions if action["consequential"] is True)
    points.append(
        SummaryPoint(
            "Consequential Actions",
            (f"{consequential} of {len(actions)}",),
            derived=True,
        )
    )
    return SummarySection("Case and Task Boundary", tuple(points))


def _verdict_section(assessment: JsonObject) -> SummarySection:
    recommended = recommendation(assessment)
    points = [
        SummaryPoint("Verdict", (_text(assessment["verdict"], "$.assessment.verdict"),)),
        SummaryPoint(
            "Verdict Rule",
            (_text(assessment["verdict_rule_id"], "$.assessment.verdict_rule_id"),),
        ),
        SummaryPoint("Recommendation", (recommended,), derived=recommended in DERIVED_MARKERS),
        SummaryPoint(
            "Evidence State",
            (_text(assessment["evidence_state"], "$.assessment.evidence_state"),),
        ),
    ]
    conditions = _list_of_objects(assessment["unmet_conditions"], "$.assessment.unmet_conditions")
    if not conditions:
        points.append(SummaryPoint("Unmet Conditions", (EMPTY,), derived=True))
    for condition in conditions:
        points.append(
            SummaryPoint(
                "Unmet Condition",
                (
                    _text(condition["id"], "$.assessment.unmet_conditions[].id"),
                    _text(condition["statement"], "$.assessment.unmet_conditions[].statement"),
                ),
            )
        )
    return SummarySection("Verdict", tuple(points))


def _decision_space_section(dossier: JsonObject) -> SummarySection:
    comparison = dossier["candidate_comparison"]
    if comparison is None:
        return SummarySection(
            "Decision Space", (SummaryPoint("Candidates", (ABSENT,), derived=True),)
        )
    candidates = _list_of_objects(
        require_object(comparison, "$.dossier.candidate_comparison")["candidates"],
        "$.dossier.candidate_comparison.candidates",
    )
    points = [
        SummaryPoint(
            "Candidate",
            (
                _text(candidate["id"], "$.dossier.candidate_comparison.candidates[].id"),
                _text(candidate["name"], "$.dossier.candidate_comparison.candidates[].name"),
                _text(
                    candidate["control_class"],
                    "$.dossier.candidate_comparison.candidates[].control_class",
                ),
                *_strings(candidate["roles"], "$.dossier.candidate_comparison.candidates[].roles"),
            ),
        )
        for candidate in candidates
    ]
    boundary = require_object(comparison, "$.dossier.candidate_comparison").get(
        "strongest_simpler_boundary"
    )
    if boundary is None:
        points.append(SummaryPoint("Strongest Simpler Alternative", (ABSENT,), derived=True))
    else:
        strongest = require_object(boundary, "$.dossier.candidate_comparison.boundary")
        points.append(
            SummaryPoint(
                "Strongest Simpler Alternative",
                (
                    _text(strongest["strongest_candidate_id"], "$.boundary.strongest_candidate_id"),
                    _text(strongest["scope"], "$.boundary.scope"),
                ),
            )
        )
    retention = require_object(comparison, "$.dossier.candidate_comparison").get(
        "baseline_retention"
    )
    if retention is not None:
        declared = require_object(retention, "$.dossier.candidate_comparison.baseline_retention")
        points.append(
            SummaryPoint(
                "Baseline Retention (Authored Decision)",
                (
                    _text(declared["declared_by"], "$.baseline_retention.declared_by"),
                    _text(declared["rationale"], "$.baseline_retention.rationale"),
                ),
            )
        )
    return SummarySection("Decision Space", tuple(points))


def _control_section(dossier: JsonObject) -> SummarySection:
    autonomy = dossier["autonomy_permission"]
    if autonomy is None:
        return SummarySection(
            "Vetoes and Mandatory Human Controls",
            (SummaryPoint("Autonomy Boundary", (ABSENT,), derived=True),),
        )
    permission = require_object(autonomy, "$.dossier.autonomy_permission")
    points: list[SummaryPoint] = []
    for veto in _list_of_objects(
        permission["hard_vetoes"], "$.dossier.autonomy_permission.hard_vetoes"
    ):
        if veto["status"] != "active":
            continue
        points.append(
            SummaryPoint(
                "Active Veto",
                (
                    _text(veto["id"], "$.hard_vetoes[].id"),
                    _text(veto["condition"], "$.hard_vetoes[].condition"),
                    _text(veto["consequence"], "$.hard_vetoes[].consequence"),
                ),
            )
        )
    for control in _list_of_objects(
        permission["mandatory_human_controls"],
        "$.dossier.autonomy_permission.mandatory_human_controls",
    ):
        points.append(
            SummaryPoint(
                "Mandatory Human Control",
                (
                    _text(control["id"], "$.mandatory_human_controls[].id"),
                    _text(control["description"], "$.mandatory_human_controls[].description"),
                    _text(control["control_point"], "$.mandatory_human_controls[].control_point"),
                    _text(
                        control["responsible_role"],
                        "$.mandatory_human_controls[].responsible_role",
                    ),
                ),
            )
        )
    if not points:
        points.append(SummaryPoint("Active Vetoes and Controls", (EMPTY,), derived=True))
    return SummarySection("Vetoes and Mandatory Human Controls", tuple(points))


def _scope_sections(record: JsonObject) -> tuple[SummarySection, ...]:
    """Render what an abstention already determines before what it still lacks (FR-019)."""
    if "abstention_scope" not in record:
        return ()
    scope = require_object(record["abstention_scope"], "$.abstention_scope")
    points: list[SummaryPoint] = []

    def determinations(name: str, label: str) -> None:
        for item in _list_of_objects(scope[name], f"$.abstention_scope.{name}"):
            control_class = _text(item["control_class"], f"$.abstention_scope.{name}[].class")
            rules = _strings(item["rule_ids"], f"$.abstention_scope.{name}[].rule_ids")
            candidates = _strings(item["candidate_ids"], f"$.abstention_scope.{name}[].candidates")
            points.append(
                SummaryPoint(
                    label,
                    (
                        control_class,
                        ("candidates: " + ", ".join(candidates)) if candidates else EMPTY,
                        ("rules: " + ", ".join(rules)) if rules else EMPTY,
                    ),
                )
            )

    determinations("eliminated_classes", "Already Eliminated")
    determinations("undetermined_classes", "Still Undetermined")
    surviving = _strings(scope["surviving_classes"], "$.abstention_scope.surviving_classes")
    points.append(
        SummaryPoint("Surviving Classes", tuple(surviving) if surviving else (EMPTY,), derived=True)
    )
    retained = scope["human_decision_retained"]
    points.append(
        SummaryPoint(
            "Human Decision Retained",
            (
                "no assistance envelope is recorded"
                if retained is None
                else ("yes" if retained is True else "no"),
            ),
            derived=True,
        )
    )
    choice = _text(scope["remaining_choice"], "$.abstention_scope.remaining_choice")
    points.append(
        SummaryPoint(
            "Remaining Choice",
            (
                "whether to assist at all; no candidate proposes to replace human decision-making"
                if choice == "assist-or-not"
                else "an unresolved autonomy question",
            ),
            derived=True,
        )
    )
    gaps = _strings(
        scope["outstanding_gap_rule_ids"], "$.abstention_scope.outstanding_gap_rule_ids"
    )
    points.append(SummaryPoint("Outstanding Gaps", tuple(gaps) if gaps else (EMPTY,), derived=True))
    return (SummarySection("Abstention Scope", tuple(points)),)


def _envelope_sections(record: JsonObject) -> tuple[SummarySection, ...]:
    """Render the FR-019 assistance envelope where the record carries one."""
    if "assistance_envelope" not in record:
        return ()
    envelope = require_object(record["assistance_envelope"], "$.assistance_envelope")
    points: list[SummaryPoint] = []
    for entry in _list_of_objects(envelope["entries"], "$.assistance_envelope.entries"):
        action = _text(entry["action_id"], "$.assistance_envelope.entries[].action_id")
        values = [
            "consequential" if entry["consequential"] else "not consequential",
            "a person must perform or approve it"
            if entry["person_required"]
            else "no recorded control or veto binds it",
        ]
        controls = _strings(
            entry["mandatory_human_control_ids"],
            "$.assistance_envelope.entries[].mandatory_human_control_ids",
        )
        vetoes = _strings(
            entry["active_hard_veto_ids"], "$.assistance_envelope.entries[].active_hard_veto_ids"
        )
        if controls:
            values.append("mandatory human controls: " + ", ".join(controls))
        if vetoes:
            values.append("active hard vetoes: " + ", ".join(vetoes))
        authorities = _list_of_objects(
            entry["declared_authorities"], "$.assistance_envelope.entries[].declared_authorities"
        )
        if not authorities:
            values.append("no represented candidate declares authority over it")
        for authority in authorities:
            candidate = _text(
                authority["candidate_id"], "$.assistance_envelope.entries[].declared_authorities[]"
            )
            control_class = _text(
                authority["control_class"],
                "$.assistance_envelope.entries[].declared_authorities[].control_class",
            )
            retained = _strings(
                authority["retained_human_control_ids"], "$.assistance_envelope.retained"
            )
            omitted = _strings(
                authority["omitted_human_control_ids"], "$.assistance_envelope.omitted"
            )
            statement = f"{candidate} ({control_class}) declares authority"
            if retained:
                statement += "; retains " + ", ".join(retained)
            if omitted:
                statement += "; does not retain " + ", ".join(omitted)
            values.append(statement)
        points.append(SummaryPoint(action, tuple(values)))
    retained_decision = envelope["human_decision_retained"] is True
    points.append(
        SummaryPoint(
            "Human Decision Retained",
            (
                "yes: no candidate proposes to replace human decision-making"
                if retained_decision
                else "no: at least one candidate proposes to act on a consequential action "
                "without a retained human control, or a consequential action has no "
                "evidenced control",
            ),
            derived=True,
        )
    )
    return (SummarySection("Assistance Envelope", tuple(points)),)


def _evidence_section(record: JsonObject, dossier: JsonObject) -> SummarySection:
    evidence = _list_of_objects(dossier["evidence"], "$.dossier.evidence")
    counts = {kind: 0 for kind in _EVIDENCE_KINDS}
    for entry in evidence:
        kind = _text(entry["kind"], "$.dossier.evidence[].kind")
        if kind not in counts:
            raise ReportRecordError(f"Decision record evidence kind {kind} is unsupported.")
        counts[kind] += 1
    points = [
        SummaryPoint(kind.title(), (str(counts[kind]),), derived=True) for kind in _EVIDENCE_KINDS
    ]
    links = require_object(record["evidence_links"], "$.evidence_links")
    gaps = 0
    for entry in evidence:
        identifier = _text(entry["id"], "$.dossier.evidence[].id")
        link = links.get(identifier)
        # Records before schema 3 carry no citation marker; every entry counted then.
        bearing = (
            require_object(link, f"$.evidence_links.{identifier}").get("decision_bearing", True)
            if link is not None
            else True
        )
        if bearing is not True:
            points.append(
                SummaryPoint(
                    "Recorded Context",
                    (identifier, _text(entry["claim"], "$.dossier.evidence[].claim")),
                )
            )
            continue
        if entry["kind"] != "missing":
            continue
        gaps += 1
        points.append(
            SummaryPoint(
                "Material Gap",
                (
                    identifier,
                    _text(entry["claim"], "$.dossier.evidence[].claim"),
                    _text(entry["resolved_by"], "$.dossier.evidence[].resolved_by"),
                ),
            )
        )
    for gap in _list_of_objects(record["unresolved_gaps"], "$.unresolved_gaps"):
        effect = _text(gap["effect"], "$.unresolved_gaps[].effect")
        non_decisive = effect == "non-decisive"
        if not non_decisive:
            gaps += 1
        points.append(
            SummaryPoint(
                "Non-Decisive Gap" if non_decisive else "Unresolved Gap",
                (
                    _text(gap["rule_id"], "$.unresolved_gaps[].rule_id"),
                    _text(gap["message"], "$.unresolved_gaps[].message"),
                ),
            )
        )
    if not gaps:
        points.append(SummaryPoint("Material Gaps", (EMPTY,), derived=True))
    return SummarySection("Evidence State", tuple(points))


def _focus_candidate_ids(dossier: JsonObject, assessment: JsonObject) -> frozenset[str]:
    """Return the candidates whose comparisons can still move the verdict.

    A surviving candidate is what the verdict rests on. When nothing survives,
    the proposed candidate is what the reader is being asked about, so its
    comparisons are the ones that explain the outcome.
    """
    surviving = _strings(
        assessment["surviving_candidate_ids"], "$.assessment.surviving_candidate_ids"
    )
    if surviving:
        return frozenset(surviving)
    comparison = dossier["candidate_comparison"]
    if comparison is None:
        return frozenset()
    candidates = _list_of_objects(
        require_object(comparison, "$.dossier.candidate_comparison")["candidates"],
        "$.dossier.candidate_comparison.candidates",
    )
    return frozenset(
        _text(candidate["id"], "$.candidates[].id")
        for candidate in candidates
        if "proposed" in _strings(candidate["roles"], "$.candidates[].roles")
    )


def _trade_off_section(dossier: JsonObject, assessment: JsonObject) -> SummarySection:
    comparison = dossier["candidate_comparison"]
    if comparison is None:
        return SummarySection(
            "Decisive Trade-offs", (SummaryPoint("Trade-offs", (ABSENT,), derived=True),)
        )
    focus = _focus_candidate_ids(dossier, assessment)
    points: list[SummaryPoint] = []
    for pair in _list_of_objects(
        require_object(comparison, "$.dossier.candidate_comparison")["comparisons"],
        "$.dossier.candidate_comparison.comparisons",
    ):
        subject = _text(pair["subject_candidate_id"], "$.comparisons[].subject_candidate_id")
        comparator = _text(
            pair["comparator_candidate_id"], "$.comparisons[].comparator_candidate_id"
        )
        if subject not in focus and comparator not in focus:
            continue
        dimensions = require_object(pair["dimensions"], "$.comparisons[].dimensions")
        for name in _DIMENSIONS:
            dimension = require_object(dimensions[name], f"$.comparisons[].dimensions.{name}")
            result = _text(dimension["result"], f"$.dimensions.{name}.result")
            if result not in _DIRECTIONAL_RESULTS:
                continue
            points.append(
                SummaryPoint(
                    f"Trade-off ({name.replace('_', ' ').title()})",
                    (
                        subject,
                        comparator,
                        result,
                        _text(dimension["rationale"], f"$.dimensions.{name}.rationale"),
                    ),
                )
            )
    if not points:
        points.append(SummaryPoint("Directional Trade-offs", (EMPTY,), derived=True))
    return SummarySection("Decisive Trade-offs", tuple(points))


def is_derived_value(value: str) -> bool:
    """Return whether ``value`` is one of the closed set of derived values."""
    return value in DERIVED_MARKERS or _DERIVED_COUNT.fullmatch(value) is not None


def build_executive_summary(record: JsonObject) -> ExecutiveSummary:
    """Return one deterministic executive summary of a loaded canonical record."""
    view = masked_record_view(record)
    masked, dossier, assessment = view.record, view.dossier, view.assessment
    case = require_object(dossier["case"], "$.dossier.case")
    return ExecutiveSummary(
        record_content_identity=_text(
            masked["record_content_identity"], "$.record_content_identity"
        ),
        ruleset_version=_text(masked["ruleset_version"], "$.ruleset_version"),
        tool_version=_text(masked["tool_version"], "$.tool_version"),
        case_title=_text(case["title"], "$.dossier.case.title"),
        language=view.language,
        sections=(
            _case_section(dossier),
            _verdict_section(assessment),
            *_scope_sections(masked),
            _decision_space_section(dossier),
            _control_section(dossier),
            *_envelope_sections(masked),
            _evidence_section(masked, dossier),
            _trade_off_section(dossier, assessment),
        ),
    )
