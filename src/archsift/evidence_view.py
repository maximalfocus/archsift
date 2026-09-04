"""The evidence-set view of a decision record (FR-021).

One row per slot of the record's dossier schema version, in profile order.
Each row lists every authored item recorded at the slot by its authored name
or description and, for every cited decision-bearing evidence entry, its state
in the neutral register and whether an accountable person has confirmed it;
where a gap flag is raised for the slot, or a cited entry is missing or of a
kind the slot's rules do not accept, the row states what would settle it. The
view lists and never tallies, introduces no fact absent from the record, and
carries no internal identifier. It is a rendering beside the ledger, the
record, and the traceability appendix, never a substitute for them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from archsift.canonical import JsonObject, JsonValue
from archsift.evidence_set import EvidenceSetProfile, Slot, evidence_set_profile
from archsift.narrative import Names, resolve_finding
from archsift.rules import RuleEffect
from archsift.validation import EvidenceKind
from archsift.vocabulary import (
    ANSWERS,
    AUTHORS,
    COMPARISON_RESULTS,
    DIMENSIONS,
    TEST_RESULTS,
    VocabularyError,
    phrase,
    term,
)

VIEW_TITLE: Final = "What the evidence says"
_OPTION_PREFIXES: Final = (
    "$.candidate_comparison.candidates[].",
    "$.candidate_comparison.comparisons[].",
)
_EMPTY: Final = "Nothing is recorded at this slot."
_INDEX: Final = re.compile(r"\[\d+\]")

#: Which slot a decision finding's criterion belongs to.
_CRITERION_SLOTS: Final[dict[str, str]] = {
    "outcome": "$.candidate_comparison.candidates[].outcome_tests[]",
    "constraint": "$.candidate_comparison.candidates[].constraint_tests[]",
    "hard-veto": "$.autonomy_permission.hard_vetoes[]",
    "human-control": "$.autonomy_permission.mandatory_human_controls[]",
    "residual-case": "$.agency_necessity.residual_cases[]",
}


@dataclass(frozen=True, slots=True)
class ViewRow:
    """One slot's row: its reader-facing name and the sentences listed under it."""

    name: str
    texts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceView:
    """The complete evidence-set view of one record."""

    dossier_schema_version: int
    vocabulary_version: str
    rows: tuple[ViewRow, ...]


def _obj(value: JsonValue, where: str) -> JsonObject:
    if type(value) is not dict:
        raise VocabularyError(f"Evidence view expected an object at {where}.")
    return value


def _str(value: JsonValue, where: str) -> str:
    if type(value) is not str:
        raise VocabularyError(f"Evidence view expected text at {where}.")
    return value


def _clause(text: str) -> str:
    return text[:-1] if text.endswith(".") else text


def _at(node: JsonValue, segments: list[str]) -> list[JsonValue]:
    """Return every value at a schema location, expanding each ``[]`` over its list."""
    if not segments:
        return [node]
    head, rest = segments[0], segments[1:]
    key = head.removesuffix("[]")
    if type(node) is not dict or key not in node or node[key] is None:
        return []
    value = node[key]
    if head.endswith("[]"):
        if type(value) is not list:
            return []
        found: list[JsonValue] = []
        for item in value:
            found.extend(_at(item, rest))
        return found
    return _at(value, rest)


def _values(dossier: JsonObject, location: str) -> list[JsonValue]:
    return _at(dossier, location.removeprefix("$.").split("."))


class _View:
    def __init__(self, record: JsonObject, profile: EvidenceSetProfile) -> None:
        self.record = record
        self.dossier = _obj(record["dossier"], "$.dossier")
        self.names = Names(self.dossier)
        self.profile = profile
        links = record.get("evidence_links")
        self.links = _obj(links, "$.evidence_links") if links is not None else {}
        self.gaps: dict[str, list[str]] = {}
        self._collect_gaps()

    # -- evidence states -----------------------------------------------------

    def _bearing(self, identifier: str) -> bool:
        link = self.links.get(identifier)
        if type(link) is dict:
            return link.get("decision_bearing", True) is not False
        return True

    def _state(self, identifier: str, slot: Slot) -> str | None:
        entry = self.names.evidence.get(identifier)
        if entry is None or not self._bearing(identifier):
            return None
        kind = EvidenceKind(_str(entry["kind"], "kind"))
        text = f"{_clause(_str(entry['claim'], 'claim'))}: {phrase(kind)}"
        if kind is EvidenceKind.OBSERVED:
            text += f" from {_clause(_str(entry['provenance'], 'provenance'))}"
        elif kind is EvidenceKind.ESTIMATE:
            text += f" by {_clause(_str(entry['method'], 'method'))}"
        authorship = entry.get("authorship")
        if type(authorship) is dict:
            author = term(AUTHORS, _str(authorship["authored_by"], "author"), "author")
            confirmed = authorship["attested_by_accountable_person"] is True
            text += f"; authored by {author}, " + (
                "confirmed by an accountable person"
                if confirmed
                else "not yet confirmed by an accountable person"
            )
        else:
            text += "; recorded by an accountable person"
        text += "."
        if kind is EvidenceKind.MISSING:
            text += f" What would settle it: {_str(entry['resolved_by'], 'resolved_by')}"
        elif kind not in slot.phrases.kinds:
            accepted = ", ".join(slot.kind_phrases)
            text += (
                f" This kind does not count as support here; what would settle it: evidence that "
                f"is {accepted}."
            )
        return text

    def _states(self, item: JsonObject, slot: Slot) -> list[str]:
        cited = item.get("evidence_ids")
        if type(cited) is not list:
            return []
        states = [self._state(_str(x, "evidence id"), slot) for x in cited]
        return [state for state in states if state is not None]

    # -- gap flags -----------------------------------------------------------

    def _slot_for_path(self, path: str) -> str:
        normalised = _INDEX.sub("[]", path)
        best: str | None = None
        for slot in self.profile.slots:
            location = slot.location
            matches = normalised == location or normalised.startswith(location + ".")
            if matches and (best is None or len(location) > len(best)):
                best = location
        if best is not None:
            return best
        # A section-level gap belongs to the first slot of that section.
        section = normalised.removeprefix("$.").split(".", 1)[0].removesuffix("[]")
        for slot in self.profile.slots:
            if slot.location.removeprefix("$.").split(".", 1)[0].removesuffix("[]") == section:
                return slot.location
        return self.profile.slots[0].location

    def _decision_slot(self, gap: JsonObject) -> str:
        """Return the slot a decision finding's criterion is recorded at."""
        kind = gap.get("criterion_kind")
        if type(kind) is str and kind in _CRITERION_SLOTS:
            return _CRITERION_SLOTS[kind]
        if kind in {"agency-question", "derived-agency"}:
            criterion = gap.get("criterion_id")
            return self._slot_for_path(
                f"$.agency_necessity.{criterion}"
                if type(criterion) is str
                else "$.agency_necessity"
            )
        return self._slot_for_path("$.candidate_comparison")

    def _collect_gaps(self) -> None:
        gaps = self.record["unresolved_gaps"]
        if type(gaps) is not list:
            raise VocabularyError("Evidence view expected a list at $.unresolved_gaps.")
        for raw in gaps:
            gap = _obj(raw, "$.unresolved_gaps[]")
            if gap["effect"] != RuleEffect.REQUIRE_EVIDENCE.value:
                continue
            source = _str(gap["source"], "source")
            location = (
                self._slot_for_path(_str(gap["field"], "field"))
                if source == "prerequisite"
                else self._decision_slot(gap)
            )
            resolved = resolve_finding(self.record, self.names, gap, source=source)
            text = (
                f"Gap flag (framework rule {resolved.framework_rule}): {resolved.message} "
                f"What would settle it: {resolved.remediation}"
            )
            entries = self.gaps.setdefault(location, [])
            if text not in entries:
                entries.append(text)

    # -- authored items ------------------------------------------------------

    def _label(self, slot: Slot, item: JsonObject, location: str) -> str:
        names = self.names
        section = location.removeprefix("$.")
        if section.startswith("problem_value.outcomes"):
            return (
                f"{_clause(_str(item['description'], 'outcome'))}: target "
                f"{_clause(_str(item['target'], 'target'))}, measured as "
                f"{_clause(_str(item['measure'], 'measure'))}"
            )
        if section.startswith("problem_value.baselines"):
            return (
                f"{_clause(_str(item['description'], 'baseline'))}: today "
                f"{_clause(_str(item['value'], 'value'))} ({_clause(_str(item['measure'], 'm'))})"
            )
        if section.startswith("problem_value.constraints"):
            return (
                f"{_clause(_str(item['description'], 'constraint'))}: must show "
                f"{_clause(_str(item['required_result'], 'required_result'))}"
            )
        if section.startswith("problem_value."):
            return _clause(_str(item["statement"], "statement"))
        if section.startswith(("agency_necessity.", "autonomy_permission.")) and "answer" in item:
            answer = term(ANSWERS, _str(item["answer"], "answer"), "answer")
            return f"{answer.capitalize()}: {_clause(_str(item['rationale'], 'rationale'))}"
        if section.startswith("agency_necessity.residual_cases"):
            return (
                f"{_clause(_str(item['description'], 'residual'))}: "
                f"{_clause(_str(item['fixed_workflow_failure'], 'failure'))}"
            )
        if section.startswith("autonomy_permission.hard_vetoes"):
            return (
                f"{_clause(_str(item['condition'], 'condition'))}: then "
                f"{_clause(_str(item['consequence'], 'consequence'))}"
            )
        if section.startswith("autonomy_permission.mandatory_human_controls"):
            return (
                f"{_clause(_str(item['description'], 'control'))}: "
                f"{_clause(_str(item['control_point'], 'when'))}, by "
                f"{_clause(_str(item['responsible_role'], 'who'))}"
            )
        if section.startswith("candidate_comparison.strongest_simpler_boundary"):
            strongest = _str(item["strongest_candidate_id"], "strongest")
            name = names.candidate(strongest) if strongest in names.candidates else strongest
            return f"{name}: {_clause(_str(item['rationale'], 'rationale'))}"
        if section.startswith("candidate_comparison.baseline_retention"):
            return (
                f"Declared by {_clause(_str(item['declared_by'], 'declared_by'))}: "
                f"{_clause(_str(item['rationale'], 'rationale'))}"
            )
        if section.startswith("decision_conditions"):
            return f"{_clause(_str(item['statement'], 'statement'))}"
        raise VocabularyError(f"Evidence view cannot name items at {location!r}.")

    def _candidate_rows(self, slot: Slot) -> list[str]:
        """Items nested under candidates and comparisons carry the option's name."""
        names = self.names
        location = slot.location
        texts: list[str] = []
        comparison = self.dossier.get("candidate_comparison")
        if comparison is None:
            return texts
        comparison_object = _obj(comparison, "$.candidate_comparison")
        if location.startswith("$.candidate_comparison.candidates[]."):
            leaf = location.removeprefix("$.candidate_comparison.candidates[].")
            for candidate in comparison_object["candidates"]:  # type: ignore[union-attr]
                candidate_object = _obj(candidate, "candidate")
                name = _str(candidate_object["name"], "name")
                if leaf == "authority":
                    authority = candidate_object.get("authority")
                    if type(authority) is not dict:
                        continue
                    actions = [
                        _clause(_str(names.actions[_str(x, "a")]["description"], "action"))
                        if _str(x, "a") in names.actions
                        else _str(x, "a")
                        for x in authority["action_ids"]  # type: ignore[union-attr]
                    ]
                    texts.append(
                        f"{name} would carry out: {'; '.join(actions)}."
                        + self._suffix(authority, slot)
                    )
                    continue
                key = leaf.removesuffix("[]")
                for test in candidate_object[key]:  # type: ignore[union-attr]
                    test_object = _obj(test, key)
                    if key == "outcome_tests":
                        criterion = names.described(
                            names.outcomes,
                            _str(test_object["outcome_id"], "outcome"),
                            "description",
                        )
                    else:
                        criterion = names.described(
                            names.constraints,
                            _str(test_object["constraint_id"], "constraint"),
                            "description",
                        )
                    result = term(TEST_RESULTS, _str(test_object["result"], "result"), "result")
                    texts.append(
                        f"{name} against {_clause(criterion)}: {result}. "
                        f"{_clause(_str(test_object['rationale'], 'rationale'))}."
                        + self._suffix(test_object, slot)
                    )
            return texts
        if location.startswith("$.candidate_comparison.comparisons[].dimensions."):
            field = location.rsplit(".", 1)[-1]
            for pair in comparison_object["comparisons"]:  # type: ignore[union-attr]
                pair_object = _obj(pair, "comparison")
                subject = names.candidate(_str(pair_object["subject_candidate_id"], "s"))
                comparator = names.candidate(_str(pair_object["comparator_candidate_id"], "c"))
                dimension = _obj(_obj(pair_object["dimensions"], "dimensions")[field], field)
                result = term(COMPARISON_RESULTS, _str(dimension["result"], "result"), "result")
                texts.append(
                    f"{subject} compared with {comparator} on {DIMENSIONS[field]}: {result}. "
                    f"{_clause(_str(dimension['rationale'], 'rationale'))}."
                    + self._suffix(dimension, slot)
                )
            return texts
        return texts

    def _suffix(self, item: JsonObject, slot: Slot) -> str:
        states = self._states(item, slot)
        return "".join(f" Evidence: {state}" for state in states)

    def _task_row(self, slot: Slot) -> list[str]:
        task = self.dossier.get("task")
        if task is None:
            return []
        task_object = _obj(task, "$.task")
        texts = [f"{_clause(_str(task_object['operation'], 'operation'))}."]
        for action in task_object["actions"]:  # type: ignore[union-attr]
            action_object = _obj(action, "action")
            weight = (
                "consequential" if action_object["consequential"] is True else "not consequential"
            )
            texts.append(f"{_clause(_str(action_object['description'], 'action'))} ({weight}).")
        return texts

    def row(self, slot: Slot) -> ViewRow:
        location = slot.location
        if location == "$.task":
            texts = self._task_row(slot)
        elif location.startswith(_OPTION_PREFIXES):
            texts = self._candidate_rows(slot)
        else:
            texts = []
            for value in _values(self.dossier, location):
                item = _obj(value, location)
                texts.append(f"{self._label(slot, item, location)}." + self._suffix(item, slot))
        texts.extend(self.gaps.get(location, ()))
        if not texts:
            texts = [_EMPTY]
        return ViewRow(slot.phrases.name, tuple(texts))


def build_evidence_view(masked_record: JsonObject) -> EvidenceView:
    """Build the evidence-set view of one masked canonical record."""
    version = masked_record["dossier_schema_version"]
    if type(version) is not int:
        raise VocabularyError("Evidence view expected an integer dossier schema version.")
    profile = evidence_set_profile(version)
    view = _View(masked_record, profile)
    return EvidenceView(
        dossier_schema_version=version,
        vocabulary_version=profile.vocabulary_version,
        rows=tuple(view.row(slot) for slot in profile.slots),
    )
