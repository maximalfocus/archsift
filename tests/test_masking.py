"""NFR-009 deterministic sensitive-value masking policy and output boundary."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from archsift.cli import main
from archsift.comparison import load_decision_record
from archsift.decision_record import (
    canonical_decision_record_bytes,
    compose_decision_record,
)
from archsift.diagnostics import ExitCode
from archsift.markdown_report import render_markdown_decision_report
from archsift.masking import (
    MASKING_POLICY_VERSION,
    MASKING_WARNING,
    mask_sensitive_text,
    masked_canonical_decision_record_bytes,
    masked_canonical_decision_record_dict,
)
from archsift.validation import (
    CaseIdentity,
    DecisionArea,
    Dossier,
    ObservedEvidence,
)
from archsift.workspace import initialize_workspace

_PLACEHOLDER_CARD = "[ARCHSIFT-MASKED:payment-card]"
_PLACEHOLDER_SSN = "[ARCHSIFT-MASKED:ssn]"
_PLACEHOLDER_ITIN = "[ARCHSIFT-MASKED:itin]"
_PLACEHOLDER_CREDENTIAL = "[ARCHSIFT-MASKED:credential]"


def _luhn_number(prefix: str, length: int = 16) -> str:
    """Return a Luhn-valid card-like number with the given leading digits."""
    digits = prefix + "0" * (length - 1 - len(prefix))
    total = 0
    double = False
    for digit in reversed(digits):
        value = ord(digit) - 48
        if double:
            value *= 2
            if value > 9:
                value -= 9
        total += value
        double = not double
    check = (10 - total % 10) % 10
    return digits[:-1] + str(check)


# --- policy v1 positive regressions -------------------------------------------------


def test_payment_cards_mask_across_documented_issuer_families() -> None:
    for card in (
        "4111 1111 1111 1111",  # Visa
        "5555 5555 5555 4444",  # Mastercard
        "3782 822463 10005",  # American Express
        "6011 1111 1111 1117",  # Discover
        "3056 9309 0259 04",  # Diners Club (4-4-4-2 printed grouping)
        "3530 1113 3330 0000",  # JCB
        "4111111111111111",  # contiguous
        "4111-1111-1111-1111",  # hyphenated
        "4012 8888 8888 1881",  # alternate Visa vector
    ):
        text = f"Card {card} here"
        assert mask_sensitive_text(text) == f"Card {_PLACEHOLDER_CARD} here"
        assert card not in mask_sensitive_text(text)


def test_card_run_with_leading_date_masks_only_the_card() -> None:
    text = "Reviewed 2026-08-15 against card 4111-1111-1111-1111 today"
    assert mask_sensitive_text(text) == (
        f"Reviewed 2026-08-15 against card {_PLACEHOLDER_CARD} today"
    )


def test_two_cards_in_one_run_and_card_with_stray_digits() -> None:
    assert mask_sensitive_text("A 4111-1111-1111-1111 and 5555-5555-5555-4444 B") == (
        f"A {_PLACEHOLDER_CARD} and {_PLACEHOLDER_CARD} B"
    )
    assert mask_sensitive_text("A 4111-1111-1111-1111 123 B") == (f"A {_PLACEHOLDER_CARD} 123 B")


def test_ssn_and_itin_shapes_mask_when_constraints_pass() -> None:
    assert mask_sensitive_text("SSN 123-45-6789 stored") == f"SSN {_PLACEHOLDER_SSN} stored"
    assert mask_sensitive_text("SSN 123 45 6789 stored") == f"SSN {_PLACEHOLDER_SSN} stored"
    assert mask_sensitive_text("ITIN 912-70-1234 kept") == f"ITIN {_PLACEHOLDER_ITIN} kept"
    assert mask_sensitive_text("ITIN 900-50-6789 kept") == f"ITIN {_PLACEHOLDER_ITIN} kept"


def test_unseparated_ssn_and_itin_mask_only_when_strongly_labelled() -> None:
    assert mask_sensitive_text("SSN: 123456789") == f"SSN: {_PLACEHOLDER_SSN}"
    assert mask_sensitive_text("SSN 123456789") == f"SSN {_PLACEHOLDER_SSN}"
    assert mask_sensitive_text("ssn=123456789") == f"ssn={_PLACEHOLDER_SSN}"
    assert mask_sensitive_text("social security number 123456789") == (
        f"social security number {_PLACEHOLDER_SSN}"
    )
    assert mask_sensitive_text("itin 912705678") == f"itin {_PLACEHOLDER_ITIN}"
    assert mask_sensitive_text("nine digits 123456789 stay") == "nine digits 123456789 stay"


def test_credential_signatures_mask_without_labels() -> None:
    vectors = (
        "AKIAIOSFODNN7EXAMPLE",  # AWS access key
        "ASIAIOSFODNN7EXAMPLE",  # AWS session key
        "ghp_123456789012345678901234567890123456",  # GitHub token
        "sk-123456789012345678901234",  # OpenAI-style key
        "sk-proj-123456789012345678901234567890123456",  # project key
        "xoxb-" + "1" * 24,  # Slack-shaped token (synthetic low-entropy vector)
        (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"  # JWT
        ),
    )
    for token in vectors:
        assert mask_sensitive_text(f"token is {token}") == (f"token is {_PLACEHOLDER_CREDENTIAL}")


def test_pem_private_key_block_masks_as_one_credential() -> None:
    block = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----"
    assert mask_sensitive_text(f"key: {block} end") == f"key: {_PLACEHOLDER_CREDENTIAL} end"


def test_strong_labels_mask_values_without_a_shape() -> None:
    for labelled in (
        "password: MyP@ssw0rd!",
        "password=correct-horse-battery-staple",
        "api_key = 1234567890abcdef",
        "client_secret: abcdef1234567890",
        "auth_token: ABCDEF1234567890",
        "access_key: 1234567890",
        "private key: xyz1234567890",
        "secret_key: 1234567890abcdef",
    ):
        assert _PLACEHOLDER_CREDENTIAL in mask_sensitive_text(labelled)


def test_ambiguous_labels_mask_only_shape_matching_values() -> None:
    token = "ghp_123456789012345678901234567890123456"
    assert mask_sensitive_text(f"token: {token}") == f"token: {_PLACEHOLDER_CREDENTIAL}"
    long = "abc123DEF456ghi789jkl012mno345pqr678"
    assert mask_sensitive_text(f"secret: {long}") == f"secret: {_PLACEHOLDER_CREDENTIAL}"
    assert mask_sensitive_text("credential: hello") == "credential: hello"


def test_short_ordinary_words_never_mask_under_labels() -> None:
    assert mask_sensitive_text("password: open") == "password: open"
    assert mask_sensitive_text("token: python") == "token: python"
    assert mask_sensitive_text("secret: hello") == "secret: hello"
    assert mask_sensitive_text("password: hunter") == "password: hunter"
    # A value with a digit is not an ordinary word and is masked.
    assert mask_sensitive_text("password: hunter2") == f"password: {_PLACEHOLDER_CREDENTIAL}"


# --- policy v1 false-positive and near-miss regressions -----------------------------


def test_dates_phone_numbers_and_plain_numbers_never_mask() -> None:
    for text in (
        "the date 2026-08-15 is fine",
        "phone 202-555-0134 stays",
        "median 12 minutes baseline",
        "m=12 baseline",
        "4111 1111 1111 1112",  # Luhn-invalid card-like
    ):
        assert mask_sensitive_text(text) == text


def test_luhn_valid_number_with_unknown_issuer_range_never_masks() -> None:
    number = _luhn_number("1234")  # Luhn-valid but 1234 is not a documented IIN
    assert mask_sensitive_text(f"reference {number} kept") == f"reference {number} kept"


def test_ssn_shapes_with_invalid_constraints_never_mask() -> None:
    for text in (
        "area 000-12-3456",
        "area 900-12-3456",  # ITIN area but group 12 is outside every ITIN group range
        "group 123-00-6789",
        "serial 123-45-0000",
        "itin 912-66-1234",  # group 66 is not an ITIN group range
    ):
        assert mask_sensitive_text(text) == text


def test_card_shaped_runs_never_leak_ssn_inside() -> None:
    assert mask_sensitive_text("4111 1111 1111 1112") == "4111 1111 1111 1112"
    # A valid 16-digit card inside a longer run is still masked; the stray
    # trailing group that would overrun the 19-digit bound stays.
    assert mask_sensitive_text("20 digits 4111 1111 1111 1111 1111 stay") == (
        f"20 digits {_PLACEHOLDER_CARD} 1111 stay"
    )
    # A 20-digit run with no valid 13-19 digit window stays entirely.
    assert mask_sensitive_text("20 digits 1234 5678 9012 3456 7891 stay") == (
        "20 digits 1234 5678 9012 3456 7891 stay"
    )


def test_masking_replaces_only_matched_values() -> None:
    text = "plain prose with a 12 minute baseline and card 4111 1111 1111 1111"
    masked = mask_sensitive_text(text)
    assert masked == f"plain prose with a 12 minute baseline and card {_PLACEHOLDER_CARD}"
    assert mask_sensitive_text(text) == masked


# --- record-level output boundary ---------------------------------------------------


def _sensitive_record():
    observed = ObservedEvidence(
        "ledger",
        "The card 4111 1111 1111 1111 was used; SSN 123-45-6789 and "
        "password: MyP@ssw0rd! were recovered.",
        "Synthetic analyst",
        (DecisionArea.PROBLEM_VALUE,),
        provenance="Synthetic ledger export",
        observed_at=date(2026, 8, 15),
    )
    dossier = Dossier(
        schema_version=1,
        case=CaseIdentity("masked-case", "Card reconciliation case"),
        evidence=(observed,),
    )
    return compose_decision_record(dossier, tool_version="0.1.0-test")


def test_masked_record_dict_masks_prose_and_preserves_structure() -> None:
    record = _sensitive_record()
    payload = masked_canonical_decision_record_dict(record)

    claim = payload["dossier"]["evidence"][0]["claim"]
    assert _PLACEHOLDER_CARD in claim
    assert _PLACEHOLDER_SSN in claim
    assert _PLACEHOLDER_CREDENTIAL in claim
    assert "4111 1111 1111 1111" not in claim
    assert "123-45-6789" not in claim
    assert "MyP@ssw0rd!" not in claim

    disclosure = payload["masking"]
    assert disclosure == {
        "applied": True,
        "policy_version": MASKING_POLICY_VERSION,
        "warning": MASKING_WARNING,
    }

    # Structural addressing is byte-preserved: the identities that address the
    # immutable record under FR-011 are never masked or substituted.
    assert payload["record_content_identity"] == record.record_content_identity
    assert payload["dossier_content_identity"] == record.dossier_content_identity
    assert payload["configuration_content_identity"] == record.configuration_content_identity
    evidence_link = payload["evidence_links"]["ledger"]
    assert evidence_link["content_identity"] == record.evidence_links[0].content_identity
    assert payload["dossier"]["evidence"][0]["id"] == "ledger"
    assert payload["dossier"]["case"]["id"] == "masked-case"


def test_masked_bytes_are_canonical_and_deterministic() -> None:
    record = _sensitive_record()
    first = masked_canonical_decision_record_bytes(record)
    second = masked_canonical_decision_record_bytes(record)

    assert first == second
    payload = json.loads(first.decode("utf-8"))
    assert payload["masking"]["applied"] is True
    assert first != canonical_decision_record_bytes(record)
    # The masked presentation is canonical JSON of its own parsed object.
    assert json.loads(first.decode("utf-8")) == payload


def test_masked_markdown_report_masks_authored_text_and_appends_notice() -> None:
    record = _sensitive_record()
    report = render_markdown_decision_report(record).decode("utf-8")

    assert "4111 1111 1111 1111" not in report
    assert "123-45-6789" not in report
    assert "MyP@ssw0rd!" not in report
    assert _PLACEHOLDER_CARD in report
    assert _PLACEHOLDER_SSN in report
    assert _PLACEHOLDER_CREDENTIAL in report
    assert "## Masking Notice" in report
    assert MASKING_WARNING in report
    # Structural values stay readable in the review view.
    assert record.record_content_identity in report
    assert "masked-case" in report
    assert "ledger" in report


# --- CLI and read-back integration --------------------------------------------------


def _write_sensitive_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "masked-case"
    assert initialize_workspace(workspace).exit_code is ExitCode.SUCCESS
    dossier = {
        "schema_version": 1,
        "case": {"id": "masked-case", "title": "Card reconciliation case"},
        "evidence": [
            {
                "id": "ledger",
                "kind": "observed",
                "claim": "The card 4111 1111 1111 1111 was used; SSN 123-45-6789 was recovered.",
                "owner": "Synthetic analyst",
                "affects": ["problem-value"],
                "provenance": "Synthetic ledger export",
                "observed_at": "2026-08-15",
                "artefacts": [],
            }
        ],
        "decision_conditions": [],
    }
    (workspace / "case.yaml").write_text(
        yaml.safe_dump(dossier, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    return workspace


def test_assess_persists_masked_outputs_with_disclosure_and_byte_identical_reuse(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _write_sensitive_workspace(tmp_path)

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    first = capsys.readouterr()
    payload = json.loads(first.out)
    identity = payload["record_content_identity"]
    target = workspace / "output" / f"sha256-{identity[7:]}.json"
    report_target = workspace / "output" / f"sha256-{identity[7:]}.md"

    assert payload["masking"]["applied"] is True
    claim = payload["dossier"]["evidence"][0]["claim"]
    assert "4111 1111 1111 1111" not in claim
    assert _PLACEHOLDER_CARD in claim
    assert _PLACEHOLDER_SSN in claim
    assert target.read_bytes() == first.out.encode("ascii")
    report = report_target.read_text(encoding="utf-8")
    assert "## Masking Notice" in report
    assert "4111 1111 1111 1111" not in report

    # Identical address inputs produce byte-identical masked outputs and reuse.
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    second = capsys.readouterr()
    assert second.out.encode("ascii") == first.out.encode("ascii")
    assert set((workspace / "output").iterdir()) == {target, report_target}


def test_assess_masked_outputs_feed_compare_and_reassess_flow(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _write_sensitive_workspace(tmp_path)
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    first = capsys.readouterr()
    identity = json.loads(first.out)["record_content_identity"]
    record_path = workspace / "output" / f"sha256-{identity[7:]}.json"

    loaded = load_decision_record(record_path, root=workspace, role="old")
    assert loaded["masking"]["applied"] is True
    assert loaded["record_content_identity"] == identity
    # The embedded dossier is masked prose that still satisfies schema v1.
    assert loaded["dossier"]["evidence"][0]["id"] == "ledger"

    # A changed dossier produces a distinct masked record and an explainable
    # comparison between the two persisted masked files.
    (workspace / "case.yaml").write_text(
        (workspace / "case.yaml").read_text(encoding="utf-8").replace("was used", "was used twice"),
        encoding="utf-8",
    )
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    second = capsys.readouterr()
    second_identity = json.loads(second.out)["record_content_identity"]
    assert second_identity != identity
    second_path = workspace / "output" / f"sha256-{second_identity[7:]}.json"

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.chdir(workspace)
    try:
        old = load_decision_record(record_path, root=Path("."), role="old")
        new = load_decision_record(second_path, root=Path("."), role="new")
        from archsift.comparison import compare_decision_records

        comparison = compare_decision_records(old, new)
    finally:
        monkeypatch.undo()
    assert old["record_content_identity"] != new["record_content_identity"]
    assert comparison["changed_evidence"]["dossier_content_identity"]["changed"] is True


def test_compare_rejects_a_masked_record_with_a_broken_masking_disclosure(
    tmp_path: Path,
) -> None:
    from archsift.canonical import canonical_json_bytes
    from archsift.comparison import ComparisonInputError

    record = _sensitive_record()
    payload = masked_canonical_decision_record_dict(record)
    payload["masking"] = {"applied": "yes"}
    broken = tmp_path / "broken-masked-record.json"
    broken.write_bytes(canonical_json_bytes(payload))

    with pytest.raises(ComparisonInputError) as captured:
        load_decision_record(broken, root=tmp_path, role="old")
    assert captured.value.category.value == "malformed-record"
