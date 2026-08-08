"""Versioned, inspectable rules for deterministic architecture assessment."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from archsift.validation import (
    Dossier,
    PrerequisiteFinding,
    evaluate_agency_necessity_readiness,
    evaluate_autonomy_permission_readiness,
    evaluate_candidate_comparison_readiness,
    evaluate_problem_value_readiness,
)

RULESET_VERSION = "1.3.0"


class RuleEffect(StrEnum):
    """Supported non-scoring consequence classes for transparent rules."""

    BLOCK = "block"
    REQUIRE_EVIDENCE = "require-evidence"
    SUPPORT_CANDIDATE = "support-candidate"


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
    """Deterministic readiness gate before architecture assessment."""

    ruleset_version: str
    ready: bool
    findings: tuple[AssessmentPrerequisiteFinding, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""
        return {
            "findings": [finding.to_dict() for finding in self.findings],
            "ready": self.ready,
            "ruleset_version": self.ruleset_version,
        }


_PREREQUISITE_CONSEQUENCE = (
    "Architecture assessment cannot proceed until this prerequisite is resolved."
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


def _decision_rule(
    identifier: str,
    effect: RuleEffect,
    description: str,
    consequence: str,
    rationale: str,
) -> RuleDefinition:
    return RuleDefinition(
        id=identifier,
        requirement="FR-009",
        effect=effect,
        description=description,
        consequence=consequence,
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
                "candidate-comparison-missing",
                "FR-008",
                "Require the candidate-comparison fact section.",
                "Architecture selection requires explicit alternatives and trade-offs.",
            ),
            _rule(
                "candidate-constraint-test-missing",
                "FR-008",
                "Require every candidate to test every problem constraint.",
                "An untested constraint leaves comparative fit undetermined.",
            ),
            _rule(
                "candidate-outcome-test-missing",
                "FR-008",
                "Require every candidate to test every problem outcome.",
                "An untested outcome leaves comparative fit undetermined.",
            ),
            _rule(
                "candidate-problem-value-missing",
                "FR-008",
                "Require problem-value criteria before checking candidate coverage.",
                "Candidate tests need the authored outcomes and constraints as their boundary.",
            ),
            _rule(
                "candidate-role-incompatible",
                "FR-008",
                "Require candidate roles to match their ordered control classes.",
                "Simpler and agentic designations must match their control-class boundaries.",
            ),
            _rule(
                "candidate-test-result-unknown",
                "FR-008",
                "Require a known result for every authored candidate test.",
                "An unknown outcome or constraint result cannot eliminate or support a class.",
            ),
            _rule(
                "credible-agency-evidence-missing",
                "FR-006",
                "Require credible support for every agency-necessity answer.",
                "An assumption or known gap cannot establish the need for runtime agency.",
            ),
            _rule(
                "credible-candidate-test-evidence-missing",
                "FR-008",
                "Require credible support for every authored candidate test.",
                "Assumptions and known gaps cannot establish candidate outcome or constraint fit.",
            ),
            _rule(
                "credible-comparison-evidence-missing",
                "FR-008",
                "Require credible support for every pairwise trade-off dimension.",
                "Assumptions and known gaps cannot establish a comparative advantage.",
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
                "comparison-result-unknown",
                "FR-008",
                "Require a known result for every pairwise trade-off dimension.",
                "An unknown trade-off leaves comparative fit undetermined.",
            ),
            _rule(
                "problem-value-missing",
                "FR-005",
                "Require the problem-value contract.",
                "A technology choice cannot precede evidence of a worthwhile problem.",
            ),
            _rule(
                "required-candidate-role-missing",
                "FR-008",
                "Require every applicable comparison role to be assigned exactly once.",
                "Missing baseline, proposal, simpler, or agentic roles make comparison ambiguous.",
            ),
            _rule(
                "required-comparison-missing",
                "FR-008",
                "Require baseline and strongest-simpler directed comparisons.",
                "The proposed and more complex candidates must face credible simpler alternatives.",
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

DECISION_RULES = tuple(
    sorted(
        (
            _decision_rule(
                "binding-constraint-failed",
                RuleEffect.BLOCK,
                "Block a candidate that credibly fails a binding constraint.",
                "The candidate is eliminated from its represented control class.",
                "A required constraint failure cannot be offset by unrelated strengths.",
            ),
            _decision_rule(
                "binding-constraint-met",
                RuleEffect.SUPPORT_CANDIDATE,
                "Support a candidate that credibly meets a binding constraint.",
                "The binding constraint supports the candidate but cannot override a block.",
                "Eligibility support must remain criterion-specific and evidence-traceable.",
            ),
            _decision_rule(
                "binding-outcome-failed",
                RuleEffect.BLOCK,
                "Block a candidate that credibly fails a binding outcome.",
                "The candidate is eliminated from its represented control class.",
                "A required outcome failure cannot be offset by unrelated strengths.",
            ),
            _decision_rule(
                "binding-outcome-met",
                RuleEffect.SUPPORT_CANDIDATE,
                "Support a candidate that credibly meets a binding outcome.",
                "The binding outcome supports the candidate but cannot override a block.",
                "Eligibility support must remain criterion-specific and evidence-traceable.",
            ),
        ),
        key=lambda rule: rule.id,
    )
)


def _verdict_rule(
    identifier: str,
    effect: RuleEffect,
    description: str,
    consequence: str,
    rationale: str,
) -> RuleDefinition:
    return RuleDefinition(
        id=identifier,
        requirement="FR-010",
        effect=effect,
        description=description,
        consequence=consequence,
        source_rationale=rationale,
    )


VERDICT_RULES = tuple(
    sorted(
        (
            _verdict_rule(
                "verdict-conditional",
                RuleEffect.SUPPORT_CANDIDATE,
                "Resolve a determined minimum-sufficient class with class-neutral "
                "unmet conditions.",
                "The determined class is conditional on every named unmet condition.",
                "A condition is valid only when satisfying it cannot change the selected class.",
            ),
            _verdict_rule(
                "verdict-insufficient-evidence",
                RuleEffect.REQUIRE_EVIDENCE,
                "Abstain when a prerequisite or potentially decisive class remains undetermined.",
                "No architecture class is recommended until the material evidence gap is resolved.",
                "Missing evidence must not promote a more complex architecture.",
            ),
            _verdict_rule(
                "verdict-no-permissible-candidate",
                RuleEffect.BLOCK,
                "Resolve complete evidenced elimination of every represented control class.",
                "No represented candidate is permissible under the current required "
                "outcomes and constraints.",
                "Complete blocking evidence is distinct from an unresolved evidence gap.",
            ),
            _verdict_rule(
                "verdict-no-technology-change",
                RuleEffect.SUPPORT_CANDIDATE,
                "Resolve human-owned work or process redesign as the minimum-sufficient class.",
                "No new automation architecture is recommended.",
                "A simpler non-technology outcome is a positive decision, not an abstention.",
            ),
            _verdict_rule(
                "verdict-supported",
                RuleEffect.SUPPORT_CANDIDATE,
                "Resolve an evidence-complete automation class as minimum sufficient.",
                "The minimum-sufficient automation class is supported by current evidence.",
                "The least surviving class is selected without ranking candidates or "
                "scoring findings.",
            ),
        ),
        key=lambda rule: rule.id,
    )
)

RULES = tuple(
    sorted((*PREREQUISITE_RULES, *DECISION_RULES, *VERDICT_RULES), key=lambda rule: rule.id)
)
_RULES_BY_ID = {rule.id: rule for rule in RULES}
if len(_RULES_BY_ID) != len(RULES):  # pragma: no cover - package invariant
    raise RuntimeError("Packaged rule IDs must be unique.")


def list_rules() -> tuple[RuleDefinition, ...]:
    """Return every immutable packaged rule in canonical order."""
    return RULES


def list_prerequisite_rules() -> tuple[RuleDefinition, ...]:
    """Return prerequisite rules in canonical order for API compatibility."""
    return PREREQUISITE_RULES


def get_rule_definition(identifier: str) -> RuleDefinition:
    """Return one packaged rule or fail on an internal catalog mismatch."""
    try:
        return _RULES_BY_ID[identifier]
    except KeyError as error:  # pragma: no cover - guarded by catalog coverage tests
        raise RuntimeError(f"No packaged rule definition for {identifier!r}.") from error


def _assessment_finding(source: PrerequisiteFinding) -> AssessmentPrerequisiteFinding:
    rule = get_rule_definition(source.id)
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
    """Compose FR-003 and FR-005 through FR-008 readiness without issuing a verdict."""
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
    source_findings.extend(evaluate_candidate_comparison_readiness(dossier).findings)
    findings = tuple(_assessment_finding(source) for source in source_findings)
    return AssessmentPrerequisiteEvaluation(
        ruleset_version=RULESET_VERSION,
        ready=not findings,
        findings=findings,
    )
