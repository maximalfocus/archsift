"""Versioned, inspectable prerequisite rules for later assessment."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from archsift.validation import (
    Dossier,
    PrerequisiteFinding,
    evaluate_agency_necessity_readiness,
    evaluate_autonomy_permission_readiness,
    evaluate_problem_value_readiness,
)

RULESET_VERSION = "1.0.0"


class RuleEffect(StrEnum):
    """Supported consequence classes for transparent decision rules."""

    REQUIRE_EVIDENCE = "require-evidence"


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """One immutable rule in the packaged ruleset."""

    id: str
    requirement: str
    effect: RuleEffect
    description: str
    consequence: str
    source_rationale: str

    def to_dict(self) -> dict[str, str]:
        """Return a deterministic JSON-compatible representation."""
        return {key: str(value) for key, value in asdict(self).items()}


@dataclass(frozen=True, slots=True)
class AssessmentPrerequisiteFinding:
    """One traceable occurrence of an unmet assessment prerequisite."""

    rule_id: str
    field: str
    requirement: str
    effect: RuleEffect
    message: str
    consequence: str
    remediation: str
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""
        return {
            "consequence": self.consequence,
            "effect": self.effect.value,
            "evidence_ids": list(self.evidence_ids),
            "field": self.field,
            "message": self.message,
            "remediation": self.remediation,
            "requirement": self.requirement,
            "rule_id": self.rule_id,
        }


@dataclass(frozen=True, slots=True)
class AssessmentPrerequisiteEvaluation:
    """Deterministic readiness gate before candidate comparison."""

    ruleset_version: str
    ready: bool
    findings: tuple[AssessmentPrerequisiteFinding, ...] = ()


_PREREQUISITE_CONSEQUENCE = (
    "Candidate comparison cannot proceed until this assessment prerequisite is resolved."
)


def _rule(identifier: str, requirement: str, description: str, rationale: str) -> RuleDefinition:
    return RuleDefinition(
        id=identifier,
        requirement=requirement,
        effect=RuleEffect.REQUIRE_EVIDENCE,
        description=description,
        consequence=_PREREQUISITE_CONSEQUENCE,
        source_rationale=rationale,
    )


# The catalog is sorted by stable rule ID so display order does not depend on
# mappings, imports, the filesystem, or authored dossier order.
PREREQUISITE_RULES = tuple(
    sorted(
        (
            _rule(
                "agency-answer-unknown",
                "FR-006",
                "Require a known answer for every agency-necessity question.",
                "Agency necessity cannot be judged from an unanswered decision question.",
            ),
            _rule(
                "agency-necessity-missing",
                "FR-006",
                "Require the agency-necessity fact section.",
                "Agency necessity is a distinct prerequisite for architecture selection.",
            ),
            _rule(
                "autonomy-answer-unknown",
                "FR-007",
                "Require a known answer for every autonomy-permission question.",
                "Autonomy permission cannot be judged from an unanswered decision question.",
            ),
            _rule(
                "autonomy-permission-missing",
                "FR-007",
                "Require the autonomy-permission fact section.",
                "Autonomy permission is separate from business value and agency necessity.",
            ),
            _rule(
                "baseline-reference-unresolved",
                "FR-005",
                "Require every binding outcome to reference an existing baseline.",
                "A measurable outcome needs a resolvable current-state comparator.",
            ),
            _rule(
                "binding-outcome-missing",
                "FR-005",
                "Require at least one measurable binding outcome.",
                "Architecture selection must be anchored to a required business outcome.",
            ),
            _rule(
                "credible-agency-evidence-missing",
                "FR-006",
                "Require credible support for every agency-necessity answer.",
                "An assumption or known gap cannot establish the need for runtime agency.",
            ),
            _rule(
                "credible-autonomy-evidence-missing",
                "FR-007",
                "Require credible support for every autonomy-permission answer.",
                "An assumption or known gap cannot establish an autonomy boundary.",
            ),
            _rule(
                "credible-baseline-missing",
                "FR-005",
                "Require a credible baseline for every binding outcome.",
                "An observed or method-backed baseline is required before comparison.",
            ),
            _rule(
                "credible-hard-veto-evidence-missing",
                "FR-007",
                "Require credible support for every hard veto.",
                "A hard boundary must remain explicit and evidence-backed rather than scored.",
            ),
            _rule(
                "credible-human-control-evidence-missing",
                "FR-007",
                "Require credible support for every mandatory human control.",
                "A mandatory control must remain explicit and evidence-backed.",
            ),
            _rule(
                "credible-residual-case-evidence-missing",
                "FR-006",
                "Require credible support for every fixed-workflow residual case.",
                "Unsupported residual cases cannot justify greater runtime freedom.",
            ),
            _rule(
                "hard-veto-status-unknown",
                "FR-007",
                "Require known applicability for every hard veto.",
                "An unresolved veto cannot be hidden or averaged into a recommendation.",
            ),
            _rule(
                "problem-value-missing",
                "FR-005",
                "Require the problem-value contract.",
                "A technology choice cannot precede evidence of a worthwhile problem.",
            ),
            _rule(
                "task-boundary-missing",
                "FR-003",
                "Require a bounded operational task and action boundary.",
                "A broad use-case label is not an assessable unit of architecture selection.",
            ),
        ),
        key=lambda rule: rule.id,
    )
)

_RULES_BY_ID = {rule.id: rule for rule in PREREQUISITE_RULES}
if len(_RULES_BY_ID) != len(PREREQUISITE_RULES):  # pragma: no cover - package invariant
    raise RuntimeError("Packaged prerequisite rule IDs must be unique.")


def list_prerequisite_rules() -> tuple[RuleDefinition, ...]:
    """Return the immutable packaged rules in canonical order."""
    return PREREQUISITE_RULES


def _assessment_finding(source: PrerequisiteFinding) -> AssessmentPrerequisiteFinding:
    try:
        rule = _RULES_BY_ID[source.id]
    except KeyError as error:  # pragma: no cover - guarded by catalog coverage tests
        raise RuntimeError(f"No packaged rule definition for finding {source.id!r}.") from error
    return AssessmentPrerequisiteFinding(
        rule_id=rule.id,
        field=source.field,
        requirement=source.requirement,
        effect=rule.effect,
        message=source.message,
        consequence=rule.consequence,
        remediation=source.remediation,
        evidence_ids=source.evidence_ids,
    )


def evaluate_assessment_prerequisites(dossier: Dossier) -> AssessmentPrerequisiteEvaluation:
    """Compose FR-003 and FR-005 through FR-007 readiness without issuing a verdict."""
    source_findings: list[PrerequisiteFinding] = []
    if dossier.task is None:
        source_findings.append(
            PrerequisiteFinding(
                id="task-boundary-missing",
                field="$.task",
                requirement="FR-003",
                message="The dossier does not define a bounded operational task.",
                remediation="Add the task boundary, actions, approval boundaries, and exclusions.",
            )
        )
    source_findings.extend(evaluate_problem_value_readiness(dossier).findings)
    source_findings.extend(evaluate_agency_necessity_readiness(dossier).findings)
    source_findings.extend(evaluate_autonomy_permission_readiness(dossier).findings)
    findings = tuple(_assessment_finding(source) for source in source_findings)
    return AssessmentPrerequisiteEvaluation(
        ruleset_version=RULESET_VERSION,
        ready=not findings,
        findings=findings,
    )
