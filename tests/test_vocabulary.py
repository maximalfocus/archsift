"""The neutral plain-language vocabulary (NFR-011)."""

from __future__ import annotations

import json
from types import MappingProxyType

import pytest

from archsift import vocabulary
from archsift.cli import main
from archsift.decision import ArchitectureVerdict, EvidenceState
from archsift.diagnostics import ExitCode
from archsift.rules import RuleEffect, list_rules
from archsift.validation import ControlClass, DecisionArea, EvidenceKind
from archsift.vocabulary import (
    EXCLUDED_WORDS,
    FLAGS,
    RULES,
    VOCABULARY_SPECIFICATION,
    VOCABULARY_VERSION,
    VocabularyError,
    excluded_words_in,
    phrase,
    rule_phrases,
    validate_vocabulary,
    vocabulary_payload,
)

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def _all_phrases(payload: dict[str, object]) -> list[str]:
    found: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk({key: value for key, value in payload.items() if key != "excluded_words"})
    return found


def test_vocabulary_covers_every_live_enumeration_and_every_packaged_rule() -> None:
    validate_vocabulary()
    payload = vocabulary_payload()
    assert payload["version"] == VOCABULARY_VERSION == "1.3.0"
    assert payload["specification"] == VOCABULARY_SPECIFICATION
    assert (ROOT / VOCABULARY_SPECIFICATION).is_file()
    assert set(payload["verdicts"]) == {item.value for item in ArchitectureVerdict}
    assert set(payload["evidence_states"]) == {item.value for item in EvidenceState}
    assert set(payload["options"]) == {item.value for item in ControlClass}
    assert set(payload["evidence_kinds"]) == {item.value for item in EvidenceKind}
    assert set(payload["decision_questions"]) == {item.value for item in DecisionArea}
    assert payload["flags"] == {
        "block": "stop",
        "require-evidence": "gap",
        "constrain-autonomy": "condition",
        "support-candidate": "fit",
        "non-decisive": "noted",
    }
    assert set(payload["flag_meanings"]) == set(payload["flags"].values())
    rules = {rule.id: rule for rule in list_rules()}
    assert set(payload["rules"]) == set(rules)
    for rule_id, entry in payload["rules"].items():
        assert entry["flag"] == FLAGS[rules[rule_id].effect]
        assert set(entry) == {"consequence", "flag", "message", "remediation"}
    assert payload["result_name"] == "result"
    assert payload["indicated_option"] == "indicated option"
    assert "accountable owner" in payload["decision_owner_statement"]
    # Exactly one fixed name per question and per option.
    assert len(set(payload["decision_questions"].values())) == 4
    assert len(set(payload["options"].values())) == 5


def test_no_vocabulary_phrase_contains_an_excluded_word() -> None:
    payload = vocabulary_payload()
    assert list(payload["excluded_words"]) == list(EXCLUDED_WORDS)
    offenders = [(text, excluded_words_in(text)) for text in _all_phrases(payload)]
    assert [item for item in offenders if item[1]] == []
    assert excluded_words_in(
        "We verified, approved and recommended it; a veto rejects certification."
    ) == (
        "verified",
        "approved",
        "recommended",
        "veto",
        "rejects",
        "certification",
    )
    assert excluded_words_in("A valid dossier with a vetoed release is still valid.") == ("vetoed",)


def test_lookup_of_an_unmapped_term_fails_closed() -> None:
    with pytest.raises(VocabularyError, match="No reader-facing phrases for rule 'no-such-rule'"):
        rule_phrases("no-such-rule")
    with pytest.raises(VocabularyError, match="No reader-facing phrase"):
        phrase("no-such-term")
    assert phrase(ArchitectureVerdict.INSUFFICIENT_EVIDENCE).startswith("more evidence is needed")
    assert phrase(RuleEffect.BLOCK) == "stop"
    assert phrase(ControlClass.AGENTIC_CONTROL) == "AI that chooses its own steps"


def test_a_phrase_with_an_excluded_word_or_a_missing_rule_fails_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tainted = dict(RULES)
    tainted["task-boundary-missing"] = vocabulary.RulePhrases(
        "gap", "The reviewer must approve the task boundary first.", "x", "y"
    )
    monkeypatch.setattr(vocabulary, "RULES", MappingProxyType(tainted))
    with pytest.raises(VocabularyError, match="excluded words approve"):
        validate_vocabulary()

    incomplete = {key: value for key, value in RULES.items() if key != "verdict-supported"}
    monkeypatch.setattr(vocabulary, "RULES", MappingProxyType(incomplete))
    with pytest.raises(
        VocabularyError, match="No reader-facing phrases for rule 'verdict-supported'"
    ):
        validate_vocabulary()

    wrong_flag = dict(RULES)
    wrong_flag["binding-outcome-failed"] = vocabulary.RulePhrases("fit", "a", "b", "c")
    monkeypatch.setattr(vocabulary, "RULES", MappingProxyType(wrong_flag))
    with pytest.raises(VocabularyError, match="carries flag 'fit'"):
        validate_vocabulary()


def test_rules_command_exposes_the_vocabulary_deterministically(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["rules", "--json"]) == ExitCode.SUCCESS
    first = capsys.readouterr().out
    assert main(["rules", "--json"]) == ExitCode.SUCCESS
    assert capsys.readouterr().out == first
    payload = json.loads(first)
    assert payload["vocabulary"] == vocabulary_payload()
    assert len(payload["vocabulary"]["rules"]) == len(payload["rules"])

    assert main(["rules"]) == ExitCode.SUCCESS
    human = capsys.readouterr().out
    assert f"Plain-language vocabulary {VOCABULARY_VERSION} ({VOCABULARY_SPECIFICATION})" in human
    assert "binding-outcome-failed [block; FR-009]" in human
    line = next(item for item in human.splitlines() if item.startswith("binding-outcome-failed "))
    assert "Flag: stop. Reads: The option cannot be the indicated option." in line
    assert main(["rules", "--quiet"]) == ExitCode.SUCCESS
    assert capsys.readouterr() == ("", "")


def test_vocabulary_is_a_rendering_input_not_a_record_input() -> None:
    # The record module never imports the vocabulary, so no phrase can reach a
    # canonical record or its identity; the golden byte tests prove the bytes.
    import archsift.decision_record as decision_record

    assert "vocabulary" not in decision_record.__dict__
    source = (ROOT / "src" / "archsift" / "decision_record.py").read_text(encoding="utf-8")
    assert "archsift.vocabulary" not in source
