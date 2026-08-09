from __future__ import annotations

import copy
import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest

from archsift.canonical import JsonObject, canonical_json_bytes
from archsift.cli import build_parser, main
from archsift.comparison import compare_decision_records, load_decision_record
from archsift.diagnostics import ExitCode

_GOLDEN = Path(__file__).parent / "golden" / "decision-record-positive-v1.json"
_INCOMPLETE_GOLDEN = Path(__file__).parent / "golden" / "decision-record-incomplete-v1.json"


def _identity(value: JsonObject) -> str:
    return f"sha256:{sha256(canonical_json_bytes(value)).hexdigest()}"


def _record() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_GOLDEN.read_bytes()))


def _rehash(record: dict[str, Any]) -> None:
    dossier = cast(JsonObject, record["dossier"])
    record["dossier_content_identity"] = _identity(dossier)
    configuration = cast(JsonObject, record["configuration"])
    record["configuration_content_identity"] = _identity(configuration)
    evidence = {entry["id"]: entry for entry in record["dossier"]["evidence"]}
    for identifier, link in record["evidence_links"].items():
        link["content_identity"] = _identity(cast(JsonObject, evidence[identifier]))
    payload = cast(
        JsonObject,
        {key: value for key, value in record.items() if key != "record_content_identity"},
    )
    record["record_content_identity"] = _identity(payload)


def _write(path: Path, record: dict[str, Any]) -> bytes:
    _rehash(record)
    content = canonical_json_bytes(cast(JsonObject, record))
    path.write_bytes(content)
    return content


def _change_evidence(record: dict[str, Any], identifier: str) -> None:
    entry = next(entry for entry in record["dossier"]["evidence"] if entry["id"] == identifier)
    entry["claim"] = f"{entry['claim']} Changed synthetic claim."


def _loaded_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[JsonObject, JsonObject]:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    _write(old_path, _record())
    _write(new_path, _record())
    monkeypatch.chdir(tmp_path)
    return (
        load_decision_record(Path("old.json"), root=Path.cwd(), role="old"),
        load_decision_record(Path("new.json"), root=Path.cwd(), role="new"),
    )


def test_compare_identical_records_has_empty_stable_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, new = _loaded_pair(tmp_path, monkeypatch)

    comparison = compare_decision_records(old, new)

    assert comparison["old_record_identity"] == comparison["new_record_identity"]
    assert comparison["verdict_delta"] == {
        "changed": False,
        "new": "conditional",
        "old": "conditional",
    }
    assert comparison["changed_evidence"]["added"] == []
    assert comparison["changed_evidence"]["changed"] == []
    assert comparison["changed_evidence"]["removed"] == []
    assert comparison["changed_rules"]["findings"] == {
        "added": [],
        "changed": [],
        "removed": [],
    }
    assert comparison["changed_verdict_fields"] == []
    assert comparison["causes"] == {"evidence_ids": [], "finding_changes": 0}
    assert comparison["context"] == {
        "evidence_ids": [],
        "finding_changes": 0,
        "snapshot_fields": [],
    }


def test_compare_accepts_current_complete_and_incomplete_canonical_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "old.json").write_bytes(_GOLDEN.read_bytes())
    (tmp_path / "new.json").write_bytes(_INCOMPLETE_GOLDEN.read_bytes())
    monkeypatch.chdir(tmp_path)

    old = load_decision_record(Path("old.json"), root=Path.cwd(), role="old")
    new = load_decision_record(Path("new.json"), root=Path.cwd(), role="new")
    comparison = compare_decision_records(old, new)

    assert comparison["verdict_delta"] == {
        "changed": True,
        "new": "insufficient-evidence",
        "old": "conditional",
    }


def test_compare_lists_added_removed_and_identity_changed_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_record = _record()
    new_record = copy.deepcopy(old_record)
    _change_evidence(new_record, "a-assumption")
    removed = next(
        entry for entry in new_record["dossier"]["evidence"] if entry["id"] == "z-missing"
    )
    new_record["dossier"]["evidence"].remove(removed)
    del new_record["evidence_links"]["z-missing"]
    added = copy.deepcopy(removed)
    added["id"] = "zz-added"
    new_record["dossier"]["evidence"].append(added)
    new_record["evidence_links"]["zz-added"] = {
        "content_identity": "sha256:" + ("0" * 64),
        "evidence_id": "zz-added",
        "kind": added["kind"],
    }
    trigger = next(
        item for item in new_record["reassessment_triggers"] if item["evidence_id"] == "z-missing"
    )
    trigger["evidence_id"] = "zz-added"
    _write(tmp_path / "old.json", old_record)
    _write(tmp_path / "new.json", new_record)
    monkeypatch.chdir(tmp_path)

    old = load_decision_record(Path("old.json"), root=Path.cwd(), role="old")
    new = load_decision_record(Path("new.json"), root=Path.cwd(), role="new")
    payload = compare_decision_records(old, new)

    assert payload["changed_evidence"]["added"] == ["zz-added"]
    assert payload["changed_evidence"]["removed"] == ["z-missing"]
    assert payload["changed_evidence"]["changed"] == ["a-assumption"]
    assert payload["changed_evidence"]["dossier_content_identity"]["changed"] is True


def test_compare_distinguishes_added_removed_and_changed_findings_and_rulesets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_record = _record()
    new_record = copy.deepcopy(old_record)
    old_findings = new_record["assessment"]["ordered_elimination_evaluation"]["findings"]
    changed = old_findings[0]
    changed["effect"] = "non-decisive"
    old_findings.pop(1)
    added = copy.deepcopy(old_findings[-1])
    added["criterion_id"] = "synthetic-added-criterion"
    added["rule_id"] = "synthetic-added-rule"
    old_findings.append(added)
    for target in (
        new_record,
        new_record["assessment"],
        new_record["assessment"]["prerequisite_evaluation"],
        new_record["assessment"]["ordered_elimination_evaluation"],
    ):
        target["ruleset_version"] = "1.9.0-synthetic"
    _write(tmp_path / "old.json", old_record)
    _write(tmp_path / "new.json", new_record)
    monkeypatch.chdir(tmp_path)

    old = load_decision_record(Path("old.json"), root=Path.cwd(), role="old")
    new = load_decision_record(Path("new.json"), root=Path.cwd(), role="new")
    comparison = compare_decision_records(old, new)
    findings = comparison["changed_rules"]["findings"]

    assert comparison["changed_rules"]["ruleset_version"]["changed"] is True
    assert len(findings["added"]) == 1
    assert len(findings["removed"]) == 1
    assert len(findings["changed"]) == 1
    assert comparison["causes"]["finding_changes"] == 0
    assert comparison["context"]["finding_changes"] == 3
    assert "ruleset_version" in comparison["context"]["snapshot_fields"]


def test_compare_names_every_changed_verdict_field_with_old_and_new_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_record = _record()
    new_record = copy.deepcopy(old_record)
    assessment = new_record["assessment"]
    assessment["verdict"] = "supported"
    assessment["verdict_rule_id"] = "synthetic-new-verdict"
    assessment["recommended_class"] = "agentic-control"
    assessment["surviving_candidate_ids"] = ["agentic"]
    assessment["evidence_state"] = "evidence-incomplete"
    assessment["unmet_conditions"] = []
    _write(tmp_path / "old.json", old_record)
    _write(tmp_path / "new.json", new_record)
    monkeypatch.chdir(tmp_path)

    old = load_decision_record(Path("old.json"), root=Path.cwd(), role="old")
    new = load_decision_record(Path("new.json"), root=Path.cwd(), role="new")
    comparison = compare_decision_records(old, new)

    assert [item["field"] for item in comparison["changed_verdict_fields"]] == [
        "verdict",
        "verdict_rule",
        "recommended_class",
        "surviving_candidate_ids",
        "evidence_state",
        "unmet_condition_ids",
    ]
    assert all(
        set(item) == {"field", "new", "old"} for item in comparison["changed_verdict_fields"]
    )


def test_compare_separates_finding_cited_cause_from_unrelated_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_record = _record()
    new_record = copy.deepcopy(old_record)
    _change_evidence(new_record, "autonomy-observed")
    _change_evidence(new_record, "a-assumption")
    new_record["assessment"]["verdict"] = "supported"
    _write(tmp_path / "old.json", old_record)
    _write(tmp_path / "new.json", new_record)
    monkeypatch.chdir(tmp_path)

    old = load_decision_record(Path("old.json"), root=Path.cwd(), role="old")
    new = load_decision_record(Path("new.json"), root=Path.cwd(), role="new")
    comparison = compare_decision_records(old, new)

    assert comparison["causes"]["evidence_ids"] == ["autonomy-observed"]
    assert comparison["context"]["evidence_ids"] == ["a-assumption"]
    assert "dossier_content_identity" in comparison["context"]["snapshot_fields"]


def test_reordered_but_identical_evidence_is_context_not_a_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_record = _record()
    new_record = copy.deepcopy(old_record)
    new_record["dossier"]["evidence"].reverse()
    _write(tmp_path / "old.json", old_record)
    _write(tmp_path / "new.json", new_record)
    monkeypatch.chdir(tmp_path)

    old = load_decision_record(Path("old.json"), root=Path.cwd(), role="old")
    new = load_decision_record(Path("new.json"), root=Path.cwd(), role="new")
    comparison = compare_decision_records(old, new)

    assert comparison["changed_evidence"]["changed"] == []
    assert comparison["causes"] == {"evidence_ids": [], "finding_changes": 0}
    assert comparison["context"]["snapshot_fields"] == ["dossier_content_identity"]


def test_compare_json_and_human_modes_are_byte_deterministic_and_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = _record()
    new = copy.deepcopy(old)
    _change_evidence(new, "a-assumption")
    old_content = _write(tmp_path / "old.json", old)
    new_content = _write(tmp_path / "new.json", new)
    before = {path.name: path.stat().st_mtime_ns for path in tmp_path.iterdir()}
    monkeypatch.chdir(tmp_path)

    outputs: list[str] = []
    for _ in range(2):
        assert main(["compare", "old.json", "new.json", "--json"]) == ExitCode.SUCCESS
        outputs.append(capsys.readouterr().out)
    assert outputs[0] == outputs[1]
    assert outputs[0].endswith("\n") and not outputs[0].endswith("\n\n")
    json.loads(outputs[0])

    human: list[str] = []
    for _ in range(2):
        assert main(["compare", "old.json", "new.json"]) == ExitCode.SUCCESS
        human.append(capsys.readouterr().out)
    assert human[0] == human[1]
    assert "Verdict:" in human[0]
    assert main(["compare", "old.json", "new.json", "--quiet"]) == ExitCode.SUCCESS
    assert capsys.readouterr() == ("", "")
    assert (tmp_path / "old.json").read_bytes() == old_content
    assert (tmp_path / "new.json").read_bytes() == new_content
    assert {path.name: path.stat().st_mtime_ns for path in tmp_path.iterdir()} == before


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"\xff", ExitCode.MALFORMED_INPUT),
        (b"{", ExitCode.MALFORMED_INPUT),
        (b'{"record_schema_version":1}\n', ExitCode.MALFORMED_INPUT),
    ],
)
def test_compare_classifies_malformed_inputs(
    content: bytes,
    expected: ExitCode,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "old.json").write_bytes(content)
    _write(tmp_path / "new.json", _record())
    monkeypatch.chdir(tmp_path)

    assert main(["compare", "old.json", "new.json", "--json"]) == expected
    diagnostic = json.loads(capsys.readouterr().out)
    assert diagnostic["exit_code"] == int(expected)
    assert diagnostic["diagnostics"][0]["file"] == "old-record"
    assert diagnostic["diagnostics"][0]["field"] == "$"
    assert diagnostic["diagnostics"][0]["requirement"] == "FR-013"
    assert diagnostic["diagnostics"][0]["remediation"]


def test_compare_classifies_unsupported_record_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = _record()
    old["record_schema_version"] = 2
    _write(tmp_path / "old.json", old)
    _write(tmp_path / "new.json", _record())
    monkeypatch.chdir(tmp_path)

    assert main(["compare", "old.json", "new.json", "--json"]) == ExitCode.UNSUPPORTED_SCHEMA
    diagnostic = json.loads(capsys.readouterr().out)["diagnostics"][0]
    assert diagnostic["field"] == "$.record_schema_version"
    assert diagnostic["id"] == "compare-unsupported-schema"


def test_compare_rejects_unknown_null_dossier_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = _record()
    old["dossier"]["case"]["unknown_null"] = None
    _write(tmp_path / "old.json", old)
    _write(tmp_path / "new.json", _record())
    monkeypatch.chdir(tmp_path)

    assert main(["compare", "old.json", "new.json", "--json"]) == ExitCode.MALFORMED_INPUT
    diagnostic = json.loads(capsys.readouterr().out)["diagnostics"][0]
    assert diagnostic["id"] == "compare-malformed-record"


def test_compare_classifies_missing_outside_looping_and_non_regular_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    _write(root / "old.json", _record())
    _write(tmp_path / "outside.json", _record())
    (root / "directory.json").mkdir()
    (root / "loop.json").symlink_to("loop.json")
    monkeypatch.chdir(root)

    cases = [
        ("missing.json", ExitCode.ARTEFACT_UNAVAILABLE, "compare-target-missing"),
        (str(tmp_path / "outside.json"), ExitCode.UNSAFE_PATH, "compare-target-outside-root"),
        ("loop.json", ExitCode.UNSAFE_PATH, "compare-target-unresolvable"),
        ("directory.json", ExitCode.UNSAFE_PATH, "compare-target-not-regular"),
    ]
    for new_path, expected, diagnostic_id in cases:
        assert main(["compare", "old.json", new_path, "--json"]) == expected
        payload = json.loads(capsys.readouterr().out)
        assert payload["diagnostics"][0]["id"] == diagnostic_id


def test_compare_classifies_unreadable_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write(tmp_path / "old.json", _record())
    _write(tmp_path / "new.json", _record())
    original_open = os.open

    def unreadable(path: str | bytes | Path, *args: object, **kwargs: object) -> Any:
        if Path(path).name == "old.json":
            raise PermissionError("synthetic unreadable record")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("archsift.comparison.os.open", unreadable)
    monkeypatch.chdir(tmp_path)

    assert main(["compare", "old.json", "new.json", "--json"]) == ExitCode.ARTEFACT_UNAVAILABLE
    assert json.loads(capsys.readouterr().out)["diagnostics"][0]["id"] == (
        "compare-target-unreadable"
    )


def test_compare_help_and_mode_contract(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    help_text = parser.format_help()
    assert "compare" in help_text

    with pytest.raises(SystemExit) as captured:
        main(["compare", "old.json", "new.json", "--json", "--quiet"])
    assert captured.value.code == ExitCode.USAGE
    assert "not allowed with argument" in capsys.readouterr().err


def test_compare_keeps_unexpected_failures_at_internal_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write(tmp_path / "old.json", _record())
    _write(tmp_path / "new.json", _record())
    monkeypatch.chdir(tmp_path)

    def fail_internally(*args: object, **kwargs: object) -> JsonObject:
        raise RuntimeError("synthetic internal failure")

    monkeypatch.setattr("archsift.cli.compare_decision_records", fail_internally)

    assert main(["compare", "old.json", "new.json", "--json"]) == ExitCode.INTERNAL_ERROR
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == ExitCode.INTERNAL_ERROR
    assert payload["diagnostics"][0]["file"] == "<internal>"
