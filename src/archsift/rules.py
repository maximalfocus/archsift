"""Versioned, inspectable rules for deterministic architecture assessment."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from archsift.method import get_method_reference, validate_method_catalog
from archsift.validation import (
    Candidate,
    CandidateRole,
    CandidateTestResult,
    Dossier,
    PrerequisiteFinding,
    evaluate_agency_necessity_readiness,
    evaluate_autonomy_permission_readiness,
    evaluate_candidate_comparison_readiness,
    evaluate_consistency_readiness,
    evaluate_problem_value_readiness,
)

RULESET_VERSION = "1.13.0"


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
    counterpart: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""
        return {
            "consequence": self.consequence,
            "counterpart": self.counterpart,
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


@dataclass(frozen=True, slots=True)
class ComparisonUnknownClassification:
    """Counterfactual materiality of one unknown pairwise comparison result."""

    field: str
    material: bool
    counterfactual_verdicts: tuple[str, ...]
    within_bound: bool


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
                "agency-necessity-contradiction",
                "FR-008",
                "Diagnose a credibly supported conflict between fixed-workflow sufficiency "
                "and a runtime adaptation need.",
                "A dossier cannot credibly claim both that a fixed workflow is sufficient "
                "and that runtime tool choice or replanning is required.",
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
                "baseline-retention-contradiction",
                "FR-008",
                "Diagnose a declared baseline retention while the current baseline credibly "
                "fails a binding outcome.",
                "An authored decision to retain the current baseline cannot stand beside "
                "credible evidence that the baseline fails a required outcome.",
            ),
            _rule(
                "binding-outcome-missing",
                "FR-005",
                "Require at least one measurable binding outcome.",
                "Architecture selection must be anchored to a required business outcome.",
            ),
            _rule(
                "candidate-authority-class-contradiction",
                "FR-008",
                "Diagnose an automation authority scope on a human-owned or process-redesign "
                "candidate.",
                "The authority contract declares task-action control, which only applies to "
                "automation candidates.",
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
                "Require eligible credible support for every agency-necessity answer.",
                "An assumption, known gap, or unattested assistant claim cannot establish the "
                "need for runtime agency.",
            ),
            _rule(
                "credible-candidate-test-evidence-missing",
                "FR-008",
                "Require eligible credible support for every authored candidate test.",
                "Assumptions, known gaps, and unattested assistant claims cannot establish "
                "candidate outcome or constraint fit.",
            ),
            _rule(
                "credible-comparison-evidence-missing",
                "FR-008",
                "Require eligible credible support for every pairwise trade-off dimension.",
                "Assumptions, known gaps, and unattested assistant claims cannot establish a "
                "comparative advantage.",
            ),
            _rule(
                "credible-autonomy-evidence-missing",
                "FR-007",
                "Require eligible credible support for every autonomy-permission answer.",
                "An assumption, known gap, or unattested assistant claim cannot establish an "
                "autonomy boundary.",
            ),
            _rule(
                "credible-baseline-missing",
                "FR-005",
                "Require an eligible credible baseline for every binding outcome.",
                "An eligible observed or method-backed baseline is required before comparison.",
            ),
            _rule(
                "credible-hard-veto-evidence-missing",
                "FR-007",
                "Require eligible credible support for every hard veto.",
                "A hard boundary must remain explicit and evidence-backed rather than scored.",
            ),
            _rule(
                "credible-human-control-evidence-missing",
                "FR-007",
                "Require eligible credible support for every mandatory human control.",
                "A mandatory control must remain explicit and evidence-backed.",
            ),
            _rule(
                "credible-residual-case-evidence-missing",
                "FR-006",
                "Require eligible credible support for every fixed-workflow residual case.",
                "Unsupported or unattested assistant residual cases cannot justify greater "
                "runtime freedom.",
            ),
            _rule(
                "credible-strongest-simpler-evidence-missing",
                "FR-008",
                "Require eligible credible support for the authored strongest-simpler boundary.",
                "An assumption, known gap, or unattested assistant claim cannot justify the "
                "selected simpler alternative.",
            ),
            _rule(
                "elicited-baseline-quantified-target",
                "FR-005",
                "Refuse an elicited baseline for an outcome whose target is quantified or "
                "undeclared.",
                "An ordinal or categorical elicitation records a judgement, not a measurement, "
                "and cannot support a numeric claim.",
            ),
            _rule(
                "fixed-workflow-residual-contradiction",
                "FR-008",
                "Diagnose a credibly supported residual case recorded while a fixed workflow "
                "is credibly sufficient.",
                "A residual case records fixed-workflow failure, contradicting fixed-workflow "
                "sufficiency.",
            ),
            _rule(
                "hard-veto-status-unknown",
                "FR-007",
                "Require known applicability for every hard veto.",
                "An unresolved veto cannot be hidden or averaged into a recommendation.",
            ),
            _rule(
                "comparison-reciprocity-contradiction",
                "FR-008",
                "Diagnose incompatible known results on both directions of a candidate pair.",
                "Directional trade-offs must be reciprocal for the same dimension; a dossier "
                "cannot claim both directions simultaneously.",
            ),
            _rule(
                "comparison-result-unknown",
                "FR-008",
                "Require a known result for every pairwise trade-off dimension.",
                "An unknown trade-off leaves comparative fit undetermined.",
            ),
            _rule(
                "non-discriminating-binding-set",
                "FR-008/FR-010",
                "Require the binding set to distinguish represented candidates or establish "
                "why the current baseline should change.",
                "Candidate ordering cannot substitute for a decision-bearing difference, and "
                "retaining the current baseline must be an authored decision rather than a "
                "default.",
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
                "comparison-result-unknown-non-decisive",
                RuleEffect.NON_DECISIVE,
                "Record a verdict-invariant unknown pairwise trade-off explicitly.",
                "The unknown comparison remains visible but does not alter the verdict.",
                "An unanswered trade-off is not material when every admissible value leaves "
                "the verdict unchanged under the packaged rules.",
                requirement="FR-008/FR-009",
            ),
            _decision_rule(
                "credible-authority-evidence-missing",
                RuleEffect.REQUIRE_EVIDENCE,
                "Require eligible observed or method-backed evidence for candidate authority "
                "scope.",
                "The automation candidate remains undetermined.",
                "An assumption, known gap, or unattested assistant claim cannot establish which "
                "consequential actions an architecture controls.",
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


def _assessment_finding(
    source: PrerequisiteFinding,
    comparison_unknowns: dict[str, ComparisonUnknownClassification],
) -> AssessmentPrerequisiteFinding:
    classification = comparison_unknowns.get(source.field)
    rule_id = source.id
    message = source.message
    remediation = source.remediation
    counterpart = source.counterpart
    if source.id == "comparison-result-unknown" and classification is not None:
        rendered = ", ".join(classification.counterfactual_verdicts)
        if not classification.within_bound:
            message = (
                f"{source.message} Materiality enumeration exceeds the packaged bound, "
                "so this unknown fails closed as material."
            )
            remediation = (
                "Resolve enough unknown trade-off dimensions to bring counterfactual "
                "enumeration within the documented bound."
            )
            counterpart = "counterfactual enumeration bound exceeded"
        elif classification.material:
            message = f"{source.message} Admissible values produce differing verdicts: {rendered}."
            counterpart = f"counterfactual verdicts: {rendered}"
        else:
            rule_id = "comparison-result-unknown-non-decisive"
            message = (
                f"{source.message} Every admissible value preserves the verdict under the "
                "packaged rules."
            )
            remediation = "Resolve the comparison when useful; it does not block this verdict."
            counterpart = f"counterfactual verdict: {rendered}"
    rule = get_rule_definition(rule_id)
    return AssessmentPrerequisiteFinding(
        rule_id=rule.id,
        field=source.field,
        requirement=rule.requirement,
        effect=rule.effect,
        message=message,
        consequence=rule.consequence,
        remediation=remediation,
        evidence_ids=source.evidence_ids,
        counterpart=counterpart,
    )


def _non_discriminating_binding_finding(
    dossier: Dossier,
) -> AssessmentPrerequisiteFinding | None:
    problem = dossier.problem_value
    comparison = dossier.candidate_comparison
    if problem is None or comparison is None or not comparison.candidates:
        return None
    if comparison.baseline_retention is not None:
        return None

    binding_outcomes = tuple(sorted(item.id for item in problem.outcomes if item.binding))
    binding_constraints = tuple(sorted(item.id for item in problem.constraints if item.binding))
    if not binding_outcomes:
        return None

    current = next(
        (
            candidate
            for candidate in comparison.candidates
            if CandidateRole.CURRENT_BASELINE in candidate.roles
        ),
        None,
    )
    if current is None:
        return None

    def outcome_results(candidate: Candidate) -> dict[str, CandidateTestResult]:
        return {test.outcome_id: test.result for test in candidate.outcome_tests}

    def constraint_results(candidate: Candidate) -> dict[str, CandidateTestResult]:
        return {test.constraint_id: test.result for test in candidate.constraint_tests}

    all_candidates_meet = all(
        all(
            outcome_results(candidate).get(identifier) is CandidateTestResult.MEETS
            for identifier in binding_outcomes
        )
        and all(
            constraint_results(candidate).get(identifier) is CandidateTestResult.MEETS
            for identifier in binding_constraints
        )
        for candidate in comparison.candidates
    )
    current_outcomes = outcome_results(current)
    current_baseline_fails = any(
        current_outcomes.get(identifier) is CandidateTestResult.FAILS
        for identifier in binding_outcomes
    )
    if not all_candidates_meet and current_baseline_fails:
        return None

    binding_outcome_text = ", ".join(binding_outcomes)
    binding_constraint_text = ", ".join(binding_constraints) or "none"
    reasons: list[str] = []
    if all_candidates_meet:
        reasons.append(
            "all represented candidates meet binding outcomes "
            f"[{binding_outcome_text}] and binding constraints [{binding_constraint_text}]"
        )
    if not current_baseline_fails:
        reasons.append(
            f"current baseline {current.id!r} fails no binding outcome [{binding_outcome_text}]"
        )

    non_binding_outcomes = tuple(sorted(item.id for item in problem.outcomes if not item.binding))
    promotion_candidates = ", ".join(non_binding_outcomes) or "none recorded"
    evidence_ids = tuple(
        sorted(
            {identifier for item in problem.outcomes for identifier in item.evidence_ids}
            | {identifier for item in problem.constraints for identifier in item.evidence_ids}
            | set(problem.material_pain.evidence_ids)
            | {
                identifier
                for candidate in comparison.candidates
                for test in candidate.outcome_tests
                for identifier in test.evidence_ids
            }
            | {
                identifier
                for candidate in comparison.candidates
                for test in candidate.constraint_tests
                for identifier in test.evidence_ids
            }
        )
    )
    rule = get_rule_definition("non-discriminating-binding-set")
    return AssessmentPrerequisiteFinding(
        rule_id=rule.id,
        field="$.problem_value.outcomes",
        requirement=rule.requirement,
        effect=rule.effect,
        message="The binding set cannot distinguish a selection: " + "; ".join(reasons) + ".",
        consequence=rule.consequence,
        remediation=(
            "Record a credible binding outcome that the current baseline fails, promote a "
            f"decision-bearing requirement from non-binding outcomes [{promotion_candidates}] "
            "or the recorded material pain at $.problem_value.material_pain, or declare at "
            "$.candidate_comparison.baseline_retention that retaining the current baseline is "
            "the intended result."
        ),
        evidence_ids=evidence_ids,
        counterpart=(
            f"binding outcomes: {binding_outcome_text}; binding constraints: "
            f"{binding_constraint_text}; non-binding outcomes: {promotion_candidates}; "
            "material pain: $.problem_value.material_pain"
        ),
    )


def evaluate_assessment_prerequisites(
    dossier: Dossier,
    comparison_unknown_classifications: tuple[ComparisonUnknownClassification, ...] = (),
) -> AssessmentPrerequisiteEvaluation:
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
    source_findings.extend(evaluate_consistency_readiness(dossier).findings)
    classifications = {
        classification.field: classification
        for classification in comparison_unknown_classifications
    }
    findings = tuple(_assessment_finding(source, classifications) for source in source_findings)
    if all(finding.effect is RuleEffect.NON_DECISIVE for finding in findings):
        non_discriminating = _non_discriminating_binding_finding(dossier)
        if non_discriminating is not None:
            findings = (*findings, non_discriminating)
    return AssessmentPrerequisiteEvaluation(
        ruleset_version=RULESET_VERSION,
        ready=all(finding.effect is RuleEffect.NON_DECISIVE for finding in findings),
        findings=findings,
    )
