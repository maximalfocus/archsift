"""Versioned public method metadata for the packaged ArchSift ruleset."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType

METHOD_VERSION = "1.0.0"
METHOD_RULESET_VERSION = "1.6.0"
METHOD_SPECIFICATION = "docs/method-v1.0.0.md"


@dataclass(frozen=True, slots=True)
class CitationDefinition:
    """One public source that informs, but does not mandate, ArchSift rules."""

    id: str
    title: str
    publisher: str
    version_date: str
    url: str
    source_type: str = "primary"

    def to_dict(self) -> dict[str, str]:
        """Return a deterministic JSON-compatible representation."""
        return {key: str(value) for key, value in asdict(self).items()}


@dataclass(frozen=True, slots=True)
class MethodReference:
    """Stable method rationale and public sources for one packaged rule."""

    rationale_id: str
    source_ids: tuple[str, ...]


METHOD_CITATIONS = tuple(
    sorted(
        (
            CitationDefinition(
                id="nist-ai-600-1",
                title=(
                    "Artificial Intelligence Risk Management Framework: "
                    "Generative Artificial Intelligence Profile"
                ),
                publisher="National Institute of Standards and Technology",
                version_date="NIST AI 600-1, July 2024",
                url="https://doi.org/10.6028/NIST.AI.600-1",
            ),
            CitationDefinition(
                id="nist-ai-rmf-1.0",
                title="Artificial Intelligence Risk Management Framework (AI RMF 1.0)",
                publisher="National Institute of Standards and Technology",
                version_date="NIST AI 100-1, January 2023",
                url="https://doi.org/10.6028/NIST.AI.100-1",
            ),
            CitationDefinition(
                id="nist-sp-800-30r1",
                title="Guide for Conducting Risk Assessments",
                publisher="National Institute of Standards and Technology",
                version_date="NIST SP 800-30 Rev. 1, September 2012",
                url="https://doi.org/10.6028/NIST.SP.800-30r1",
            ),
            CitationDefinition(
                id="nist-sp-800-53r5",
                title="Security and Privacy Controls for Information Systems and Organizations",
                publisher="National Institute of Standards and Technology",
                version_date="NIST SP 800-53 Rev. 5, September 2020; updated December 2020",
                url="https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final",
            ),
            CitationDefinition(
                id="oecd-ai-principles-2024",
                title="Recommendation of the Council on Artificial Intelligence",
                publisher="Organisation for Economic Co-operation and Development",
                version_date="OECD/LEGAL/0449, adopted 2019; amended 2024",
                url="https://legalinstruments.oecd.org/en/instruments/OECD-LEGAL-0449",
            ),
            CitationDefinition(
                id="w3c-prov-o-2013",
                title="PROV-O: The PROV Ontology",
                publisher="World Wide Web Consortium",
                version_date="W3C Recommendation, 30 April 2013",
                url="https://www.w3.org/TR/2013/REC-prov-o-20130430/",
            ),
        ),
        key=lambda citation: citation.id,
    )
)
_CITATIONS_BY_ID: Mapping[str, CitationDefinition] = MappingProxyType(
    {citation.id: citation for citation in METHOD_CITATIONS}
)

# Each rule appears in exactly one group. Group IDs are stable anchors in the
# versioned Markdown specification; source IDs resolve through METHOD_CITATIONS.
_RULE_GROUPS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "agency-necessity",
        ("nist-ai-600-1", "nist-ai-rmf-1.0"),
        (
            "agency-answer-unknown",
            "agentic-agency-answer-unknown",
            "agentic-agency-fact-non-decisive",
            "agentic-agency-necessity-missing",
            "agentic-credible-agency-evidence-missing",
            "agentic-credible-residual-evidence-missing",
            "agentic-dynamic-execution-supports-agency",
            "agentic-feedback-supports-agency",
            "agentic-feedback-unavailable-blocks-candidate",
            "agentic-fixed-workflow-insufficiency-supports-agency",
            "agentic-fixed-workflow-sufficient-blocks-candidate",
            "agentic-residual-case-missing",
            "agentic-residual-case-supports-agency",
            "agentic-runtime-adaptation-missing",
            "agentic-runtime-adaptation-supports-agency",
        ),
    ),
    (
        "autonomy-boundaries",
        ("nist-ai-rmf-1.0", "nist-sp-800-53r5", "oecd-ai-principles-2024"),
        (
            "active-veto-applicability-missing",
            "active-veto-blocks-candidate",
            "automation-authority-missing",
            "autonomy-answer-unknown",
            "autonomy-boundary-non-decisive",
            "hard-veto-status-unknown",
            "mandatory-human-control-omitted",
            "mandatory-human-control-retained",
            "overlapping-veto-status-unknown",
        ),
    ),
    (
        "bounded-task",
        ("nist-ai-rmf-1.0",),
        ("task-boundary-missing",),
    ),
    (
        "candidate-comparison",
        ("nist-ai-rmf-1.0", "nist-sp-800-30r1"),
        (
            "candidate-constraint-test-missing",
            "candidate-outcome-test-missing",
            "candidate-role-incompatible",
            "candidate-test-result-unknown",
            "comparison-result-unknown",
            "required-candidate-role-missing",
            "required-comparison-missing",
        ),
    ),
    (
        "credible-evidence",
        ("nist-ai-rmf-1.0", "w3c-prov-o-2013"),
        (
            "credible-agency-evidence-missing",
            "credible-authority-evidence-missing",
            "credible-autonomy-evidence-missing",
            "credible-baseline-missing",
            "credible-candidate-test-evidence-missing",
            "credible-comparison-evidence-missing",
            "credible-hard-veto-evidence-missing",
            "credible-human-control-evidence-missing",
            "credible-residual-case-evidence-missing",
        ),
    ),
    (
        "ordered-elimination",
        ("nist-ai-rmf-1.0", "nist-sp-800-30r1"),
        (
            "binding-constraint-failed",
            "binding-constraint-met",
            "binding-outcome-failed",
            "binding-outcome-met",
        ),
    ),
    (
        "problem-value",
        ("nist-ai-rmf-1.0", "nist-sp-800-30r1"),
        (
            "baseline-reference-unresolved",
            "binding-outcome-missing",
            "problem-value-missing",
        ),
    ),
    (
        "separate-decisions",
        ("nist-ai-rmf-1.0", "oecd-ai-principles-2024"),
        (
            "agency-necessity-missing",
            "autonomy-permission-missing",
            "candidate-comparison-missing",
            "candidate-problem-value-missing",
        ),
    ),
    (
        "verdict-resolution",
        ("nist-ai-rmf-1.0", "nist-sp-800-30r1"),
        (
            "verdict-conditional",
            "verdict-insufficient-evidence",
            "verdict-no-permissible-candidate",
            "verdict-no-technology-change",
            "verdict-supported",
        ),
    ),
)


def _build_rule_references(
    groups: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = _RULE_GROUPS,
) -> dict[str, MethodReference]:
    references: dict[str, MethodReference] = {}
    for section_id, source_ids, rule_ids in groups:
        rationale_id = f"method-v{METHOD_VERSION}#{section_id}"
        for rule_id in rule_ids:
            if rule_id in references:  # pragma: no cover - package invariant
                raise RuntimeError(f"Duplicate method mapping for rule {rule_id!r}.")
            references[rule_id] = MethodReference(rationale_id, source_ids)
    return dict(sorted(references.items()))


RULE_METHOD_REFERENCES: Mapping[str, MethodReference] = MappingProxyType(_build_rule_references())


def list_method_citations() -> tuple[CitationDefinition, ...]:
    """Return the public citation registry in canonical order."""
    return METHOD_CITATIONS


def get_method_reference(rule_id: str) -> MethodReference:
    """Resolve one packaged rule to its stable public method rationale."""
    try:
        return RULE_METHOD_REFERENCES[rule_id]
    except KeyError as error:  # pragma: no cover - guarded by catalog validation
        raise RuntimeError(f"No public method mapping for rule {rule_id!r}.") from error


def method_metadata() -> dict[str, object]:
    """Return deterministic metadata for the versioned public method."""
    return {
        "ruleset_version": METHOD_RULESET_VERSION,
        "sources": [citation.to_dict() for citation in METHOD_CITATIONS],
        "specification": METHOD_SPECIFICATION,
        "version": METHOD_VERSION,
    }


def validate_method_catalog(
    ruleset_version: str,
    rule_ids: tuple[str, ...],
    references: Mapping[str, MethodReference] = RULE_METHOD_REFERENCES,
) -> None:
    """Fail closed when the ruleset and public method mapping diverge."""
    if ruleset_version != METHOD_RULESET_VERSION:
        raise RuntimeError(
            "Public method ruleset version mismatch: "
            f"expected {METHOD_RULESET_VERSION!r}, received {ruleset_version!r}."
        )
    if len(rule_ids) != len(set(rule_ids)):
        raise RuntimeError("Packaged rule IDs contain a duplicate method mapping.")
    if rule_ids != tuple(sorted(rule_ids)):
        raise RuntimeError("Packaged rule IDs must be canonical before method validation.")
    reference_ids = tuple(references)
    if reference_ids != tuple(sorted(reference_ids)):
        raise RuntimeError("Public method mappings must be in canonical rule-ID order.")
    missing = sorted(set(rule_ids) - set(reference_ids))
    dangling = sorted(set(reference_ids) - set(rule_ids))
    if missing:
        raise RuntimeError(f"Rules missing public method mappings: {missing!r}.")
    if dangling:
        raise RuntimeError(f"Public method mappings reference unknown rules: {dangling!r}.")

    known_sources = set(_CITATIONS_BY_ID)
    used_sources: set[str] = set()
    for rule_id, reference in references.items():
        if not reference.rationale_id.startswith(f"method-v{METHOD_VERSION}#"):
            raise RuntimeError(f"Rule {rule_id!r} has a non-versioned rationale identifier.")
        if not reference.source_ids:
            raise RuntimeError(f"Rule {rule_id!r} has no public source mapping.")
        if reference.source_ids != tuple(sorted(reference.source_ids)):
            raise RuntimeError(f"Rule {rule_id!r} source IDs are not canonical.")
        unknown_sources = sorted(set(reference.source_ids) - known_sources)
        if unknown_sources:
            raise RuntimeError(
                f"Rule {rule_id!r} references unknown public sources: {unknown_sources!r}."
            )
        used_sources.update(reference.source_ids)
    unused_sources = sorted(known_sources - used_sources)
    if unused_sources:
        raise RuntimeError(f"Public method sources are not mapped to a rule: {unused_sources!r}.")
