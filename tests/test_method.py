from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from archsift.method import (
    METHOD_CITATIONS,
    METHOD_RULESET_VERSION,
    METHOD_SPECIFICATION,
    METHOD_VERSION,
    RULE_METHOD_REFERENCES,
    _build_rule_references,
    validate_method_catalog,
)
from archsift.rules import RULESET_VERSION, list_rules

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_public_method_mapping_is_complete_canonical_and_version_matched() -> None:
    rules = list_rules()
    rule_ids = tuple(rule.id for rule in rules)

    validate_method_catalog(RULESET_VERSION, rule_ids)

    assert RULESET_VERSION == METHOD_RULESET_VERSION == "1.12.0"
    assert METHOD_VERSION == "1.6.0"
    assert METHOD_SPECIFICATION == "docs/method-v1.6.0.md"
    assert tuple(RULE_METHOD_REFERENCES) == rule_ids
    assert len(rule_ids) == len(RULE_METHOD_REFERENCES) == 68
    assert all(rule.rationale_id == RULE_METHOD_REFERENCES[rule.id].rationale_id for rule in rules)
    assert all(rule.source_ids == RULE_METHOD_REFERENCES[rule.id].source_ids for rule in rules)


def test_public_method_validation_rejects_catalog_drift() -> None:
    rule_ids = tuple(rule.id for rule in list_rules())

    with pytest.raises(RuntimeError, match="version mismatch"):
        validate_method_catalog("changed", rule_ids)
    with pytest.raises(RuntimeError, match="duplicate"):
        validate_method_catalog(RULESET_VERSION, tuple(sorted((*rule_ids, rule_ids[0]))))
    with pytest.raises(RuntimeError, match="canonical"):
        validate_method_catalog(RULESET_VERSION, tuple(reversed(rule_ids)))

    duplicate_group = (
        (
            "duplicate",
            ("nist-ai-rmf-1.0",),
            (rule_ids[0], rule_ids[0]),
        ),
    )
    with pytest.raises(RuntimeError, match="Duplicate method mapping"):
        _build_rule_references(duplicate_group)

    noncanonical = dict(reversed(tuple(RULE_METHOD_REFERENCES.items())))
    with pytest.raises(RuntimeError, match="canonical rule-ID order"):
        validate_method_catalog(RULESET_VERSION, rule_ids, noncanonical)

    missing = dict(RULE_METHOD_REFERENCES)
    missing.pop(rule_ids[0])
    with pytest.raises(RuntimeError, match="missing public method mappings"):
        validate_method_catalog(RULESET_VERSION, rule_ids, dict(sorted(missing.items())))

    dangling = {
        **RULE_METHOD_REFERENCES,
        "unknown-rule": RULE_METHOD_REFERENCES[rule_ids[0]],
    }
    with pytest.raises(RuntimeError, match="unknown rules"):
        validate_method_catalog(RULESET_VERSION, rule_ids, dict(sorted(dangling.items())))

    unknown_source = dict(RULE_METHOD_REFERENCES)
    unknown_source[rule_ids[0]] = replace(
        unknown_source[rule_ids[0]], source_ids=("unknown-source",)
    )
    with pytest.raises(RuntimeError, match="unknown public sources"):
        validate_method_catalog(RULESET_VERSION, rule_ids, unknown_source)

    noncanonical_sources = dict(RULE_METHOD_REFERENCES)
    target = next(
        rule_id
        for rule_id, reference in noncanonical_sources.items()
        if len(reference.source_ids) > 1
    )
    noncanonical_sources[target] = replace(
        noncanonical_sources[target],
        source_ids=tuple(reversed(noncanonical_sources[target].source_ids)),
    )
    with pytest.raises(RuntimeError, match="source IDs are not canonical"):
        validate_method_catalog(RULESET_VERSION, rule_ids, noncanonical_sources)


def test_versioned_method_document_matches_packaged_metadata() -> None:
    document = (_REPOSITORY_ROOT / METHOD_SPECIFICATION).read_text(encoding="utf-8")
    rules = list_rules()

    assert f"# ArchSift method specification {METHOD_VERSION}" in document
    assert f"**Ruleset version:** `{RULESET_VERSION}`" in document
    assert "ArchSift does **not** prove:" in document
    assert "does **not** prove global optimality" in document
    assert "general cross-section contradiction diagnostics" in document
    assert "docs/method-v1.0.0.md" not in document
    assert (_REPOSITORY_ROOT / "docs/method-v1.0.0.md").is_file()
    assert "Runtime evaluation and `archsift rules` never fetch or open citation URLs." in document

    index_rows = re.findall(
        r"^\| `(?P<rule>[^`]+)` \| `(?P<rationale>method-v[^`]+)` \| "
        r"(?P<sources>(?:`[^`]+`(?:, )?)+) \|$",
        document,
        flags=re.MULTILINE,
    )
    assert len(index_rows) == len(rules) == 68
    assert [row[0] for row in index_rows] == [rule.id for rule in rules]
    for rule, (_, rationale_id, sources) in zip(rules, index_rows, strict=True):
        assert rationale_id == rule.rationale_id
        assert tuple(re.findall(r"`([^`]+)`", sources)) == rule.source_ids
        section_id = rationale_id.split("#", maxsplit=1)[1]
        assert f'<a id="{section_id}"></a>' in document

    assert [citation.id for citation in METHOD_CITATIONS] == sorted(
        citation.id for citation in METHOD_CITATIONS
    )
    assert all(citation.source_type == "primary" for citation in METHOD_CITATIONS)
    assert all(citation.url.startswith("https://") for citation in METHOD_CITATIONS)
    for citation in METHOD_CITATIONS:
        assert f"### `{citation.id}`" in document
        assert f"- **Title:** *{citation.title}*" in document
        assert f"- **Publisher:** {citation.publisher}" in document
        assert f"- **Version/date:** {citation.version_date}" in document
        assert f"- **URL:** {citation.url}" in document
