"""Deterministic machine-readable surfaces for external dossier authors."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import cast

from archsift.canonical import (
    JsonObject,
    canonical_json_bytes,
    dossier_content_identity,
)
from archsift.decision import evaluate_assessment
from archsift.rules import RULESET_VERSION, RuleEffect
from archsift.validation import Dossier, packaged_dossier_schema

PREREQUISITE_WORKLIST_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class DossierSchemaSurface:
    """One canonical packaged dossier-schema publication."""

    schema_version: int
    content: JsonObject
    canonical_bytes: bytes
    content_identity: str
    top_level_properties: tuple[str, ...]
    definition_count: int


def dossier_schema_surface(schema_version: int) -> DossierSchemaSurface:
    """Return canonical bytes and safe inventory for one packaged dossier schema."""
    content = cast(JsonObject, dict(packaged_dossier_schema(schema_version)))
    canonical = canonical_json_bytes(content)
    properties = content.get("properties")
    definitions = content.get("$defs")
    if type(properties) is not dict or type(definitions) is not dict:
        raise TypeError("Packaged dossier schema lacks its object inventory.")
    return DossierSchemaSurface(
        schema_version=schema_version,
        content=content,
        canonical_bytes=canonical,
        content_identity=f"sha256:{sha256(canonical).hexdigest()}",
        top_level_properties=tuple(sorted(properties)),
        definition_count=len(definitions),
    )


def prerequisite_worklist(dossier: Dossier) -> JsonObject:
    """Return only outstanding findings from the assessment's prerequisite gate."""
    evaluation = evaluate_assessment(dossier).prerequisite_evaluation
    if evaluation.ruleset_version != RULESET_VERSION:
        raise ValueError("Prerequisite evaluation ruleset is inconsistent.")
    outstanding = tuple(
        finding for finding in evaluation.findings if finding.effect is not RuleEffect.NON_DECISIVE
    )
    return {
        "complete": not outstanding,
        "dossier_content_identity": dossier_content_identity(dossier),
        "dossier_schema_version": dossier.schema_version,
        "findings": [cast(JsonObject, finding.to_dict()) for finding in outstanding],
        "prerequisite_worklist_schema_version": PREREQUISITE_WORKLIST_SCHEMA_VERSION,
        "ruleset_version": evaluation.ruleset_version,
    }
