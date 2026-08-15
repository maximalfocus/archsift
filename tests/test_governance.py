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
    ROOT / ".github" / "pull_request_template.md",
)
REQUIRED_BOUNDARY_TERMS = (
    "actual case material",
    "sanitised",
    "paraphrased",
    "transformed",
    "source-mapped",
)
SENSITIVE_CASE_MATERIAL = re.compile(
    r"\b(?:actual case material|saniti[sz]ed|paraphrased|transformed|source-mapped)\b",
    re.IGNORECASE,
)
APPROVED_BOUNDARY_PASSAGES = {
    ROOT / "CONTRIBUTING.md": (
        "do not commit generated build output, virtual environments, credentials, actual case "
        "material or a sanitised, paraphrased, transformed, or source-mapped derivative, or "
        "proprietary policy text.",
        "never publish actual case material or a sanitised, paraphrased, transformed, or "
        "source-mapped derivative.",
    ),
    ROOT / ".github" / "ISSUE_TEMPLATE" / "feature_request.yml": (
        "this request contains no actual case material or sanitised, paraphrased, transformed, "
        "or source-mapped derivative.",
    ),
    ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml": (
        "this report uses an independently authored synthetic reproduction and contains no "
        "actual case material or sanitised, paraphrased, transformed, or source-mapped "
        "derivative;",
    ),
    ROOT / ".github" / "pull_request_template.md": (
        "evidence is independently authored synthetic material; no actual case material or "
        "sanitised, paraphrased, transformed, or source-mapped derivative is included;",
    ),
}


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


def _assert_safe_public_guidance(guidance: str, path: Path) -> None:
    normalized = " ".join(guidance.casefold().split())
    assert "independently authored synthetic" in normalized, path
    for boundary in REQUIRED_BOUNDARY_TERMS:
        assert boundary in normalized, (path, boundary)

    unapproved = normalized
    for passage in APPROVED_BOUNDARY_PASSAGES[path]:
        assert unapproved.count(passage) == 1, (path, passage)
        unapproved = unapproved.replace(passage, "", 1)
    assert SENSITIVE_CASE_MATERIAL.search(unapproved) is None, path


def test_public_contribution_entry_points_require_independent_synthetic_evidence() -> None:
    for path in CONTRIBUTION_ENTRY_POINTS:
        guidance = path.read_text(encoding="utf-8")
        _assert_safe_public_guidance(guidance, path)


@pytest.mark.parametrize(
    "solicitation",
    (
        "Attach actual case material for maintainers to review.",
        "A sanitised case study is required.",
        "Sanitised evidence must be uploaded.",
        "Publish actual case material or a sanitised, paraphrased, transformed, or "
        "source-mapped derivative.",
        "Commit actual case material or a sanitised, paraphrased, transformed, or "
        "source-mapped derivative.",
        "A sanitised case study is requested.",
        "Include sanitised case material but never private identifiers.",
        "We invite sanitised case studies.",
        "Sanitised case material is welcome.",
        "We encourage sanitised evidence.",
        "Please solicit sanitised case data.",
    ),
)
def test_public_contribution_boundary_rejects_positive_solicitation(
    solicitation: str,
) -> None:
    valid_guidance = CONTRIBUTION_ENTRY_POINTS[0].read_text(encoding="utf-8")
    with pytest.raises(AssertionError):
        _assert_safe_public_guidance(
            f"{valid_guidance}\n{solicitation}", CONTRIBUTION_ENTRY_POINTS[0]
        )


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
    assert re.search(r"\bno\b", privacy_confirmation)

    fields = _fields_by_id(form)
    assert set(fields) == expected_fields
    assert all(field["validations"]["required"] is True for field in fields.values())
    evidence_field = fields["problem"] if name == "feature_request.yml" else fields["reproduction"]
    assert (
        "independently authored synthetic" in evidence_field["attributes"]["description"].casefold()
    )


def test_issue_template_directory_is_exhaustively_covered() -> None:
    template_dir = ROOT / ".github" / "ISSUE_TEMPLATE"
    yaml_files = {*template_dir.glob("*.yml"), *template_dir.glob("*.yaml")}
    form_files = {
        path.name for path in yaml_files if path.name not in {"config.yml", "config.yaml"}
    }
    assert form_files == {"bug_report.yml", "feature_request.yml"}
    assert {path.name for path in yaml_files if path.name in {"config.yml", "config.yaml"}} == {
        "config.yml"
    }


def test_issue_template_configuration_keeps_private_security_route() -> None:
    path = ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml"
    configuration = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert configuration["blank_issues_enabled"] is False
    links = configuration["contact_links"]
    assert len(links) == 1
    assert links[0]["url"] == ("https://github.com/maximalfocus/archsift/security/advisories/new")


def test_publication_status_is_explicit_and_conservative() -> None:
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").casefold().split())

    assert "only this implementation repository is intended for public source publication" in readme
    assert "private requirements" in readme
    assert "private case dossiers" in readme
    assert "repository visibility does not publish a package" in readme
    assert "none of those publication events has occurred" in readme
    assert "independent cli usability cohort" in readme
    assert "independent architecture-method review" in readme
    assert "have not been completed" in readme
    assert "no usability, method-validation" in readme
    assert "production-readiness" in readme
    assert "first-release success claim is made" in readme


def test_usage_reference_covers_every_command_and_option() -> None:
    """The shipped usage reference must stay current with the CLI surface."""
    from archsift.cli import build_parser

    parser = build_parser()
    usage = (ROOT / "docs" / "usage.md").read_text(encoding="utf-8")
    commands: set[str] = set()
    options: set[str] = {"--version"}
    for action in parser._actions:  # argparse internals: the subparsers action
        choices = getattr(action, "choices", None)
        if not choices:
            continue
        commands.update(choices)
        for subparser in choices.values():
            for sub_action in subparser._actions:
                options.update(sub_action.option_strings)

    for command in sorted(commands):
        assert f"`archsift {command}" in usage or f"`{command}`" in usage, command
    for option in sorted(options):
        assert f"`{option}`" in usage, option
