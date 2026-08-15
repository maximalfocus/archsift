"""Deterministic offline sensitive-value masking for decision-record output.

Policy v1 (``MASKING_POLICY_VERSION``) implements NFR-009: before serialising
or persisting either FR-011 decision-record representation, every case-derived
or graph-authored string selected for output is passed through
:func:`mask_sensitive_text`. Assessment and rule evaluation always use the
original input; masking is a mechanical output-safety transformation and never
changes content truth, provenance, evidential acceptability, confidentiality,
or the canonical dossier bytes and cited-evidence content identities that
address the immutable record under FR-011.

Policy v1 matching rules (version-controlled in this module):

1. **PEM private-key blocks** — ``-----BEGIN <kind> PRIVATE KEY-----`` through
   the matching ``-----END <kind> PRIVATE KEY-----`` line are masked as a
   credential. Headers are matched exactly as conventionally written.
2. **Credential signatures** (no label required): AWS access keys
   ``AKIA``/``ASIA`` plus 16 uppercase base-32 characters; GitHub tokens
   ``ghp_``/``gho_``/``ghu_``/``ghs_``/``ghr_`` plus 36 alphanumerics;
   OpenAI-style keys ``sk-`` plus 20-64 alphanumerics and ``sk-proj-`` plus
   24-96 alphanumerics; Slack tokens ``xox[baprs]-`` plus 10-80 token
   characters; JSON Web Tokens starting ``eyJ`` with two dotted segments.
3. **Payment-card numbers**: a maximal run of digits separated by single
   spaces or hyphens is split into digit groups; each window of consecutive
   groups (13-19 digits total, any group sizes) is checked from the widest to
   the narrowest, and the first window that passes the Luhn check and whose
   leading digits match a documented issuer-identification range is masked
   (Visa 4; Mastercard 51-55 and 2221-2720; American Express 34 and 37;
   Discover 6011, 622126-622925, 644-649 and 65; Diners Club 300-305, 3095,
   36, 38 and 39; JCB 3528-3589). Dates, phone numbers and other digit runs
   that fail the validity gates remain unmasked; a window is accepted only
   when its own digits pass Luhn and the issuer gate.
4. **Separated SSN/ITIN shapes** — ``NNN-NN-NNNN`` or ``NNN NN NNNN`` with
   word-like boundaries. An area of 001-899 must pass the documented SSN
   area/group/serial constraints (area not 000 and at most 899, group 01-99,
   serial 0001-9999); an area of 900-999 must pass the documented ITIN
   constraints (group in 50-65, 70-88, 90-92 or 94-99, serial 0001-9999).
5. **Unseparated nine-digit SSN/ITIN values** are masked only when strongly
   labelled by a recognised label (``ssn``, ``ss#``, ``social security``,
   ``social security number``, ``itin``, ``taxpayer identification number``,
   ``tax id``) directly before the digits, with the same area/group/serial
   constraints.
6. **Strongly labelled credentials** — the value after a recognised strong
   label (``password``, ``passwd``, ``api_key``/``api-key``/``api key``,
   ``access_key``/``access key``, ``client_secret``/``client secret``,
   ``auth_token``/``auth token``, ``secret_key``/``secret key``,
   ``private_key``/``private key``) followed by ``:`` or ``=`` is masked as a
   credential. The label is unambiguous, so no value shape is required.
7. **Prose-ambiguous labels** — the value after ``secret``, ``token`` or
   ``credential(s)`` followed by ``:`` or ``=`` is masked only when it matches
   a documented credential shape (any policy signature, or 24+ characters of
   base64-style characters containing both a letter and a digit).

   A short ordinary word (1-7 alphabetic characters) remains unmasked in
   every labelled rule, so ``password: open`` and ``token: python`` stay as
   written; a short all-letter password is a documented, deliberate
   incompleteness of the high-precision policy.

Matches from earlier rules win over overlapping later matches. Only the
matched value is replaced, with these fixed category placeholders:
``[ARCHSIFT-MASKED:payment-card]``, ``[ARCHSIFT-MASKED:ssn]``,
``[ARCHSIFT-MASKED:itin]`` and ``[ARCHSIFT-MASKED:credential]``.

In both representations, structural fields (identifiers, references, paths,
content identities, versions, controlled vocabularies and non-text scalars)
are never masked: masking them would corrupt the internal references and the
immutable-record addressing required by FR-011, and would mangle the record's
own identities in the review view. Every authored string selected for output
in either representation is masked.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from archsift.canonical import JsonObject, JsonValue, canonical_json_bytes
from archsift.decision_record import DecisionRecord, canonical_decision_record_dict

MASKING_POLICY_VERSION: Final = 1

_PLACEHOLDER_PAYMENT_CARD: Final = "[ARCHSIFT-MASKED:payment-card]"
_PLACEHOLDER_SSN: Final = "[ARCHSIFT-MASKED:ssn]"
_PLACEHOLDER_ITIN: Final = "[ARCHSIFT-MASKED:itin]"
_PLACEHOLDER_CREDENTIAL: Final = "[ARCHSIFT-MASKED:credential]"

MASKING_WARNING: Final = (
    "This record was emitted with deterministic sensitive-value masking "
    "(policy version 1). It is not guaranteed to be sensitive-data-free and "
    "still requires handling appropriate to its source material."
)


class MaskingError(ValueError):
    """A decision record cannot be masked without breaking its structure."""


@dataclass(frozen=True, slots=True)
class _Replacement:
    """One accepted span replacement in the original text."""

    start: int
    end: int
    placeholder: str


_PEM_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

_SIGNATURE_PATTERN = re.compile(
    r"(?:AKIA|ASIA)[0-9A-Z]{16}"  # AWS access and session keys
    r"|(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}"  # GitHub tokens
    r"|sk-[A-Za-z0-9]{20,64}"  # OpenAI-style secret keys
    r"|sk-proj-[A-Za-z0-9]{24,96}"  # OpenAI-style project keys
    r"|xox[baprs]-[A-Za-z0-9-]{10,80}"  # Slack tokens
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"  # JWTs
)

# A maximal run of digits with optional single space/hyphen separators. The
# boundary guards keep the run from starting or ending inside a longer digit
# sequence.
_CARD_RUN_PATTERN = re.compile(r"(?<![-\d])(?<![-\d][- ])\d(?:[ -]?\d)*(?![\d-])(?![- ]\d)")
_CARD_GROUP_PATTERN = re.compile(r"\d+")

# Documented issuer-identification ranges; each pair has equal-length bounds.
_IIN_RANGES: Final[tuple[tuple[int, int], ...]] = (
    (4, 4),  # Visa
    (51, 55),  # Mastercard
    (2221, 2720),  # Mastercard 2-series
    (34, 34),  # American Express
    (37, 37),  # American Express
    (6011, 6011),  # Discover
    (622126, 622925),  # Discover
    (644, 649),  # Discover
    (65, 65),  # Discover
    (300, 305),  # Diners Club
    (3095, 3095),  # Diners Club
    (36, 36),  # Diners Club
    (38, 38),  # Diners Club
    (39, 39),  # Diners Club
    (3528, 3589),  # JCB
)

_SSN_ITIN_SEPARATED_PATTERN = re.compile(
    r"(?<![-\d])(?<![-\d][- ])\d{3}[- ]\d{2}[- ]\d{4}(?![\d-])(?![- ]\d)"
)

_LABELLED_UNSEPARATED_PATTERN = re.compile(
    r"(?i)(?<![\w-])(?:ssn|ss#|social security(?: number)?|itin"
    r"|taxpayer identification number|tax id)\s*[:=]?\s*(\d{9})(?![\d-])"
)

_STRONG_LABEL_PATTERN = re.compile(
    r"(?i)(?<![\w-])(?:password|passwd|api[ _-]?key|access[ _-]?key"
    r"|client[ _-]?secret|auth[ _-]?token|secret[ _-]?key|private[ _-]?key)"
    r"\s*[:=]\s*(?P<value>\S+)"
)

_AMBIGUOUS_LABEL_PATTERN = re.compile(
    r"(?i)(?<![\w-])(?:secret|token|credential|credentials)\s*[:=]\s*"
    r"(?P<value>\S+)"
)

_BASE64ISH_SHAPE = re.compile(r"(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9+/=_\-]{24,}")
_SHORT_ORDINARY_WORD = re.compile(r"[A-Za-z]{1,7}")
_TRAILING_LABEL_PUNCTUATION = ",.;:!?"

# Structural JSON keys that are references, addresses, versions, controlled
# vocabularies or non-text scalars. Masking these would corrupt the record's
# internal references and the immutable-record addressing under FR-011.
STRUCTURAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        # identifiers and references
        "id",
        "evidence_id",
        "artefact_id",
        "candidate_id",
        "constraint_id",
        "outcome_id",
        "baseline_id",
        "subject_candidate_id",
        "comparator_candidate_id",
        "strongest_candidate_id",
        "considered_candidate_ids",
        "criterion_id",
        "rule_id",
        "verdict_rule_id",
        "action_ids",
        "retained_human_control_ids",
        "active_hard_veto_ids",
        "mandatory_human_control_ids",
        "surviving_candidate_ids",
        "evidence_ids",
        "field",
        "counterpart",
        # paths, roots and content identities
        "path",
        "root",
        "content_identity",
        "record_content_identity",
        "dossier_content_identity",
        "configuration_content_identity",
        # versions and tool metadata
        "schema_version",
        "record_schema_version",
        "dossier_schema_version",
        "ruleset_version",
        "tool_version",
        # controlled vocabularies
        "kind",
        "status",
        "answer",
        "result",
        "effect",
        "source",
        "decision_area",
        "target_control_class",
        "control_class",
        "criterion_kind",
        "roles",
        "affects",
        "recommended_class",
        "least_surviving_class",
        "prohibited_control_classes",
        # non-text scalars and the masking disclosure
        "observed_at",
        "ready",
        "consequential",
        "byte_length",
        "masking",
    }
)


def _luhn_valid(digits: str) -> bool:
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
    return total % 10 == 0


def _iin_matches(number: str) -> bool:
    for low, high in _IIN_RANGES:
        length = len(str(low))
        prefix = int(number[:length])
        if low <= prefix <= high:
            return True
    return False


def _card_replacements(text: str) -> Iterable[_Replacement]:
    for run in _CARD_RUN_PATTERN.finditer(text):
        groups = [
            (run.start() + group.start(), group.group(0))
            for group in _CARD_GROUP_PATTERN.finditer(run.group(0))
        ]
        covered_until = -1
        for index in range(len(groups)):
            start = groups[index][0]
            if start < covered_until:
                continue
            end = index
            total = 0
            while end < len(groups) and total + len(groups[end][1]) <= 19:
                total += len(groups[end][1])
                end += 1
            while end > index and total >= 13:
                candidate = groups[index:end]
                number = "".join(group for _, group in candidate)
                if _luhn_valid(number) and _iin_matches(number):
                    end_position = candidate[-1][0] + len(candidate[-1][1])
                    yield _Replacement(start, end_position, _PLACEHOLDER_PAYMENT_CARD)
                    covered_until = end_position
                    break
                end -= 1
                total -= len(groups[end][1])


def _ssn_or_itin_replacement(
    area: str,
    group: str,
    serial: str,
    start: int,
    end: int,
) -> _Replacement | None:
    area_value = int(area)
    group_value = int(group)
    serial_value = int(serial)
    if serial_value < 1:
        return None
    if area_value <= 899:
        if area_value < 1 or group_value < 1:
            return None
        return _Replacement(start, end, _PLACEHOLDER_SSN)
    if (
        group_value in range(50, 66)
        or group_value in range(70, 89)
        or group_value in range(90, 93)
        or group_value in range(94, 100)
    ):
        return _Replacement(start, end, _PLACEHOLDER_ITIN)
    return None


def _separated_ssn_itin_replacements(text: str) -> Iterable[_Replacement]:
    for match in _SSN_ITIN_SEPARATED_PATTERN.finditer(text):
        area, group, serial = [part for part in re.split(r"[- ]", match.group(0)) if part]
        replacement = _ssn_or_itin_replacement(area, group, serial, match.start(), match.end())
        if replacement is not None:
            yield replacement


def _labelled_unseparated_replacement(text: str) -> Iterable[_Replacement]:
    for match in _LABELLED_UNSEPARATED_PATTERN.finditer(text):
        digits = match.group(1)
        area, group, serial = digits[:3], digits[3:5], digits[5:]
        replacement = _ssn_or_itin_replacement(area, group, serial, match.start(1), match.end(1))
        if replacement is not None:
            yield replacement


def _label_value_replacement(match: re.Match[str], *, require_shape: bool) -> _Replacement | None:
    value = match.group("value")
    value_start = match.start("value")
    stripped = value.rstrip(_TRAILING_LABEL_PUNCTUATION)
    if not stripped or _SHORT_ORDINARY_WORD.fullmatch(stripped):
        return None
    if (
        require_shape
        and _SIGNATURE_PATTERN.search(stripped) is None
        and _BASE64ISH_SHAPE.fullmatch(stripped) is None
    ):
        return None
    return _Replacement(value_start, value_start + len(stripped), _PLACEHOLDER_CREDENTIAL)


def _find_replacements(text: str) -> list[_Replacement]:
    accepted: list[_Replacement] = []

    def accepts(candidate: _Replacement) -> bool:
        for current in accepted:
            if candidate.start < current.end and current.start < candidate.end:
                return False
        return True

    def consider(proposals: Iterable[_Replacement]) -> None:
        for candidate in proposals:
            if accepts(candidate):
                accepted.append(candidate)

    consider(
        _Replacement(match.start(), match.end(), _PLACEHOLDER_CREDENTIAL)
        for match in _PEM_PATTERN.finditer(text)
    )
    consider(
        _Replacement(m.start(), m.end(), _PLACEHOLDER_CREDENTIAL)
        for m in _SIGNATURE_PATTERN.finditer(text)
    )
    consider(_card_replacements(text))
    consider(_separated_ssn_itin_replacements(text))
    consider(_labelled_unseparated_replacement(text))
    consider(
        replacement
        for match in _STRONG_LABEL_PATTERN.finditer(text)
        for replacement in [_label_value_replacement(match, require_shape=False)]
        if replacement is not None
    )
    consider(
        replacement
        for match in _AMBIGUOUS_LABEL_PATTERN.finditer(text)
        for replacement in [_label_value_replacement(match, require_shape=True)]
        if replacement is not None
    )
    return sorted(accepted, key=lambda item: item.start)


def mask_sensitive_text(text: str) -> str:
    """Return ``text`` with every policy-v1 matched sensitive value replaced."""
    replacements = _find_replacements(text)
    if not replacements:
        return text
    parts: list[str] = []
    cursor = 0
    for replacement in replacements:
        parts.append(text[cursor : replacement.start])
        parts.append(replacement.placeholder)
        cursor = replacement.end
    parts.append(text[cursor:])
    return "".join(parts)


def _mask_json_value(value: JsonValue, *, key: str | None) -> JsonValue:
    if key in STRUCTURAL_KEYS:
        return value
    if type(value) is str:
        return mask_sensitive_text(value)
    if type(value) is list:
        return [_mask_json_value(item, key=key) for item in value]
    if type(value) is dict:
        return {name: _mask_json_value(item, key=name) for name, item in value.items()}
    return value


def masked_canonical_decision_record_dict(record: DecisionRecord) -> JsonObject:
    """Return the masked presentation of one canonical decision record.

    The canonical dossier bytes, evidence content identities and record content
    identity that address the immutable record under FR-011 are preserved
    exactly; only emitted field values are masked, and the masking disclosure
    identifies the transformation and its policy version.
    """
    value = canonical_decision_record_dict(record)
    if type(value) is not dict:
        raise MaskingError("Decision record cannot be masked as JSON data.")
    masked = _mask_json_value(value, key=None)
    if type(masked) is not dict:
        raise MaskingError("Decision record masking produced no JSON object.")
    masked["masking"] = {
        "applied": True,
        "policy_version": MASKING_POLICY_VERSION,
        "warning": MASKING_WARNING,
    }
    return masked


def masked_canonical_decision_record_bytes(record: DecisionRecord) -> bytes:
    """Return strict canonical JSON bytes for one masked decision record."""
    return canonical_json_bytes(masked_canonical_decision_record_dict(record))


def masked_decision_record_view(record: JsonObject) -> JsonObject:
    """Return the masked presentation of one already-loaded canonical record.

    A record read back from disk was normally masked when it was persisted.
    Masking is idempotent — a fixed category placeholder matches no policy
    pattern — so re-applying it neither double-masks a persisted record nor
    lets an unmasked record reach a rendered report unmasked. The disclosure
    is restated identically, so a masked record round-trips unchanged.
    """
    masked = _mask_json_value(record, key=None)
    if type(masked) is not dict:
        raise MaskingError("Decision record masking produced no JSON object.")
    masked["masking"] = {
        "applied": True,
        "policy_version": MASKING_POLICY_VERSION,
        "warning": MASKING_WARNING,
    }
    return masked
