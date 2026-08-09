from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRIBUTION_ENTRY_POINTS = (
    ROOT / "CONTRIBUTING.md",
    ROOT / ".github" / "ISSUE_TEMPLATE" / "feature_request.yml",
    ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml",
)
REQUIRED_BOUNDARY_TERMS = (
    "actual case material",
    "sanitised",
    "paraphrased",
    "transformed",
    "source-mapped",
)
SOLICITS_SANITISED_DERIVATIVE = re.compile(
    r"\b(?:attach|describe|include|provide|submit|upload)\b[^.\n]{0,100}\bsaniti[sz]ed\b",
    re.IGNORECASE,
)


def _load_issue_form(name: str) -> dict[str, Any]:
    path = ROOT / ".github" / "ISSUE_TEMPLATE" / name
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _fields_by_id(form: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for item in form["body"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def test_public_contribution_entry_points_require_independent_synthetic_evidence() -> None:
    for path in CONTRIBUTION_ENTRY_POINTS:
        guidance = path.read_text(encoding="utf-8")
        normalized = guidance.casefold()
        assert "independently authored synthetic" in normalized, path
        assert SOLICITS_SANITISED_DERIVATIVE.search(guidance) is None, path
        for boundary in REQUIRED_BOUNDARY_TERMS:
            assert boundary in normalized, (path, boundary)


@pytest.mark.parametrize(
    ("name", "expected_name", "expected_label", "expected_fields"),
    (
        (
            "feature_request.yml",
            "Feature request",
            "enhancement",
            {"problem", "outcome", "alternatives", "non_goals"},
        ),
        (
            "bug_report.yml",
            "Bug report",
            "bug",
            {"version", "reproduction", "expected", "actual", "environment"},
        ),
    ),
)
def test_issue_forms_preserve_required_workflow(
    name: str,
    expected_name: str,
    expected_label: str,
    expected_fields: set[str],
) -> None:
    form = _load_issue_form(name)
    assert form["name"] == expected_name
    assert form["labels"] == [expected_label]
    assert isinstance(form["title"], str) and form["title"]

    preflight = form["body"][0]
    assert preflight["type"] == "checkboxes"
    assert preflight["attributes"]["label"] == "Preflight"
    assert len(preflight["attributes"]["options"]) == 2
    assert all(option["required"] is True for option in preflight["attributes"]["options"])
    privacy_confirmation = preflight["attributes"]["options"][1]["label"].casefold()
    for boundary in REQUIRED_BOUNDARY_TERMS:
        assert boundary in privacy_confirmation

    fields = _fields_by_id(form)
    assert set(fields) == expected_fields
    assert all(field["validations"]["required"] is True for field in fields.values())
    evidence_field = fields["problem"] if name == "feature_request.yml" else fields["reproduction"]
    assert (
        "independently authored synthetic" in evidence_field["attributes"]["description"].casefold()
    )


def test_issue_template_configuration_keeps_private_security_route() -> None:
    path = ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml"
    configuration = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert configuration["blank_issues_enabled"] is False
    links = configuration["contact_links"]
    assert len(links) == 1
    assert links[0]["url"] == ("https://github.com/maximalfocus/archsift/security/advisories/new")
