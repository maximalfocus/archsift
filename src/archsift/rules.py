"""Versioned, inspectable rules for deterministic architecture assessment."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from archsift.method import get_method_reference, validate_method_catalog
from archsift.validation import (
    Dossier,
    PrerequisiteFinding,
    evaluate_agency_necessity_readiness,
    evaluate_autonomy_permission_readiness,
    evaluate_candidate_comparison_readiness,
    evaluate_problem_value_readiness,
)

RULESET_VERSION = "1.7.0"


class RuleEffect(StrEnum):
    """Supported non-scoring consequence classes for transparent rules."""

    BLOCK = "block"
    REQUIRE_EVIDENCE = "require-evidence"
    SUPPORT_CANDIDATE = "support-candidate"
    CONSTRAIN_AUTONOMY = "constrain-autonomy"
    NON_DECISIVE = "non-decisive"


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """One immutable rule in the packaged ruleset."""

    id: str
    requirement: str
    effect: RuleEffect
    description: str
    consequence: str
    source_rationale: str
    rationale_id: str
    source_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""
        payload: dict[str, object] = asdict(self)
        payload["effect"] = self.effect.value
        payload["source_ids"] = list(self.source_ids)
        return payload


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
    method = get_method_reference(identifier)
    return RuleDefinition(
        id=identifier,
        requirement=requirement,
        effect=RuleEffect.REQUIRE_EVIDENCE,
        description=description,
        consequence=_PREREQUISITE_CONSEQUENCE,
        source_rationale=rationale,
        rationale_id=method.rationale_id,
        source_ids=method.source_ids,
    )


def _decision_rule(
    identifier: str,
    effect: RuleEffect,
    description: str,
    consequence: str,
    rationale: str,
    requirement: str = "FR-009",
) -> RuleDefinition:
    method = get_method_reference(identifier)
    return RuleDefinition(
        id=identifier,
        requirement=requirement,
        effect=effect,
        description=description,
        consequence=consequence,
        source_rationale=rationale,
        rationale_id=method.rationale_id,
        source_ids=method.source_ids,
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
                "credible-strongest-simpler-evidence-missing",
                "FR-008",
                "Require credible support for the authored strongest-simpler boundary.",
                "An assumption or known gap cannot justify the selected simpler alternative.",
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
                "strongest-simpler-boundary-coverage-missing",
                "FR-008",
                "Require the authored boundary to cover every represented simpler candidate.",
                "Omitting a represented simpler alternative makes the selected boundary "
                "incomplete.",
            ),
            _rule(
                "strongest-simpler-boundary-incompatible",
                "FR-008",
                "Require the authored boundary to match applicable candidate roles and classes.",
                "A boundary cannot justify a different, absent, or non-simpler candidate.",
            ),
            _rule(
                "strongest-simpler-boundary-missing",
                "FR-008",
                "Require an explicit strongest-simpler boundary for a non-human proposal.",
                "A role label alone cannot establish the strongest represented simpler option.",
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
                "active-veto-applicability-missing",
                RuleEffect.REQUIRE_EVIDENCE,
                "Require explicit prohibited control classes for an overlapping active veto.",
                "The affected automation candidate remains undetermined.",
                "A prose consequence cannot be parsed into machine-enforceable class scope.",
                requirement="FR-007/FR-009",
            ),
            _decision_rule(
                "active-veto-blocks-candidate",
                RuleEffect.BLOCK,
                "Block an automation candidate prohibited by an overlapping active veto.",
                "The candidate is eliminated from its represented control class.",
                "An active hard boundary cannot be offset by unrelated candidate strengths.",
                requirement="FR-007/FR-009",
            ),
            _decision_rule(
                "automation-authority-missing",
                RuleEffect.REQUIRE_EVIDENCE,
                "Require a credible task-action authority scope for every automation candidate.",
                "The automation candidate remains undetermined.",
                "Autonomy boundaries cannot be applied without knowing which actions a candidate "
                "controls.",
                requirement="FR-007/FR-009",
            ),
            _decision_rule(
                "autonomy-boundary-non-decisive",
                RuleEffect.NON_DECISIVE,
                "Record an inactive or non-overlapping autonomy boundary explicitly.",
                "The boundary has no effect on this candidate's disposition.",
                "Required autonomy facts must be causally accounted for even when they do not "
                "apply.",
                requirement="FR-007/FR-009",
            ),
            _decision_rule(
                "agentic-agency-answer-unknown",
                RuleEffect.REQUIRE_EVIDENCE,
                "Require a known answer for every agentic candidate agency question.",
                "The agentic candidate remains undetermined.",
                "Runtime agency cannot be established while a required structured fact is unknown.",
                requirement="FR-006/FR-009",
            ),
            _decision_rule(
                "agentic-agency-fact-non-decisive",
                RuleEffect.NON_DECISIVE,
                "Record a known agency fact that does not change the runtime-agency contract.",
                "The fact has no effect on this agentic candidate's disposition.",
                "Monitorability and facts that do not establish dynamic execution remain "
                "visible without being reinterpreted as permission or necessity.",
                requirement="FR-006/FR-009",
            ),
            _decision_rule(
                "agentic-agency-necessity-missing",
                RuleEffect.REQUIRE_EVIDENCE,
                "Require the agency-necessity fact section for every agentic candidate.",
                "The agentic candidate remains undetermined.",
                "Agentic control cannot survive without an explicit runtime-agency fact boundary.",
                requirement="FR-006/FR-009",
            ),
            _decision_rule(
                "agentic-credible-agency-evidence-missing",
                RuleEffect.REQUIRE_EVIDENCE,
                "Require observed or method-backed evidence for each agentic agency answer.",
                "The agentic candidate remains undetermined.",
                "Assumptions and known gaps cannot establish a runtime-agency fact.",
                requirement="FR-006/FR-009",
            ),
            _decision_rule(
                "agentic-credible-residual-evidence-missing",
                RuleEffect.REQUIRE_EVIDENCE,
                "Require observed or method-backed evidence for each agentic residual case.",
                "The agentic candidate remains undetermined.",
                "An unsupported residual case cannot establish fixed-workflow insufficiency.",
                requirement="FR-006/FR-009",
            ),
            _decision_rule(
                "agentic-dynamic-execution-supports-agency",
                RuleEffect.SUPPORT_CANDIDATE,
                "Support agentic necessity with credible non-predefinable or unpredictable "
                "execution.",
                "The fact supports agency necessity but cannot override a block or evidence gap.",
                "Dynamic execution is supporting context, not a substitute for runtime "
                "adaptation and fixed-workflow insufficiency.",
                requirement="FR-006/FR-009",
            ),
            _decision_rule(
                "agentic-feedback-supports-agency",
                RuleEffect.SUPPORT_CANDIDATE,
                "Support agentic necessity when environmental feedback is credibly available.",
                "The fact supports agency necessity but cannot override a block or evidence gap.",
                "The agentic class revises execution using environmental feedback.",
                requirement="FR-006/FR-009",
            ),
            _decision_rule(
                "agentic-feedback-unavailable-blocks-candidate",
                RuleEffect.BLOCK,
                "Block agentic control when environmental feedback is credibly unavailable.",
                "The agentic candidate is eliminated from its represented control class.",
                "Without environmental feedback, the defined agentic control loop cannot operate.",
                requirement="FR-006/FR-009",
            ),
            _decision_rule(
                "agentic-fixed-workflow-insufficiency-supports-agency",
                RuleEffect.SUPPORT_CANDIDATE,
                "Support agentic necessity when a fixed workflow is credibly insufficient.",
                "The fact supports agency necessity but still requires a credible residual case.",
                "Greater runtime freedom requires explicit evidence that fixed control is "
                "insufficient.",
                requirement="FR-006/FR-009",
            ),
            _decision_rule(
                "agentic-fixed-workflow-sufficient-blocks-candidate",
                RuleEffect.BLOCK,
                "Block agentic control when a fixed workflow is credibly sufficient.",
                "The agentic candidate is eliminated from its represented control class.",
                "A sufficient fixed workflow makes greater runtime freedom unnecessary.",
                requirement="FR-006/FR-009",
            ),
            _decision_rule(
                "agentic-residual-case-missing",
                RuleEffect.REQUIRE_EVIDENCE,
                "Require a residual case when fixed-workflow insufficiency is asserted.",
                "The agentic candidate remains undetermined.",
                "A conclusion of fixed-workflow insufficiency needs a concrete evidenced case.",
                requirement="FR-006/FR-009",
            ),
            _decision_rule(
                "agentic-residual-case-supports-agency",
                RuleEffect.SUPPORT_CANDIDATE,
                "Support agentic necessity with a credible fixed-workflow residual case.",
                "The residual supports agency necessity but cannot override a block or gap.",
                "A concrete residual case keeps the claim of fixed-workflow insufficiency "
                "evidence-traceable.",
                requirement="FR-006/FR-009",
            ),
            _decision_rule(
                "agentic-runtime-adaptation-missing",
                RuleEffect.BLOCK,
                "Block agentic control when neither runtime tool choice nor replanning is "
                "required.",
                "The agentic candidate is eliminated from its represented control class.",
                "Agentic control is unnecessary when no runtime model-directed adaptation is "
                "needed.",
                requirement="FR-006/FR-009",
            ),
            _decision_rule(
                "agentic-runtime-adaptation-supports-agency",
                RuleEffect.SUPPORT_CANDIDATE,
                "Support agentic necessity with credible runtime tool choice or replanning.",
                "The fact supports agency necessity but cannot override a block or evidence gap.",
                "At least one structured runtime-adaptation need is required for agentic control.",
                requirement="FR-006/FR-009",
            ),
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
            _decision_rule(
                "credible-authority-evidence-missing",
                RuleEffect.REQUIRE_EVIDENCE,
                "Require observed or method-backed evidence for candidate authority scope.",
                "The automation candidate remains undetermined.",
                "An assumption or known gap cannot establish which consequential actions an "
                "architecture controls.",
                requirement="FR-007/FR-009",
            ),
            _decision_rule(
                "overlapping-veto-status-unknown",
                RuleEffect.REQUIRE_EVIDENCE,
                "Require known status for an overlapping hard veto.",
                "The affected automation candidate remains undetermined.",
                "A boundary with unknown status cannot be treated as inactive when it overlaps "
                "candidate authority.",
                requirement="FR-007/FR-009",
            ),
            _decision_rule(
                "mandatory-human-control-omitted",
                RuleEffect.BLOCK,
                "Block a candidate that omits an applicable mandatory human control.",
                "The candidate is eliminated from its represented control class.",
                "A mandatory human boundary cannot be averaged away or treated as report-only.",
                requirement="FR-007/FR-009",
            ),
            _decision_rule(
                "mandatory-human-control-retained",
                RuleEffect.CONSTRAIN_AUTONOMY,
                "Constrain a candidate to retain an applicable mandatory human control.",
                "The candidate may remain eligible only with the named human control retained.",
                "A preserved control is an architecture boundary, not an unmet future condition.",
                requirement="FR-007/FR-009",
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
    method = get_method_reference(identifier)
    return RuleDefinition(
        id=identifier,
        requirement="FR-010",
        effect=effect,
        description=description,
        consequence=consequence,
        source_rationale=rationale,
        rationale_id=method.rationale_id,
        source_ids=method.source_ids,
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
validate_method_catalog(RULESET_VERSION, tuple(rule.id for rule in RULES))


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
