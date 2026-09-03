from __future__ import annotations

import json
import shutil
from importlib.resources import files
from pathlib import Path
from typing import cast

import pytest

from archsift.canonical import JsonObject
from archsift.case_view import CaseViewRequest, FindingBinding, construct_case_view
from archsift.cli import main
from archsift.corpus import packaged_corpus_bytes, packaged_corpus_snapshot
from archsift.diagnostics import ExitCode
from archsift.graph_change import load_graph_change_proposal, validate_graph_change
from archsift.knowledge_graph import (
    Lifecycle,
    NodeKind,
    RelationKind,
    canonical_snapshot_bytes,
    load_snapshot,
)
from archsift.method import METHOD_CITATIONS
from archsift.rules import list_rules

_REPOSITORY = Path(__file__).parent.parent
_REQUEST = _REPOSITORY / "examples" / "graph-corpus-request.json"


def test_packaged_corpus_is_the_exact_governed_evolution() -> None:
    content = packaged_corpus_bytes()
    snapshot = packaged_corpus_snapshot()
    proposal_content = (
        files("archsift").joinpath("knowledge/architecture-v3.change.json").read_bytes()
    )
    base = load_snapshot(files("archsift").joinpath("knowledge/architecture-v2.json").read_bytes())
    proposal = load_graph_change_proposal(proposal_content)

    assert load_snapshot(content) == snapshot
    assert canonical_snapshot_bytes(snapshot) == content
    assert proposal["change_kind"] == "evolution"
    assert proposal["base_snapshot"] is not None
    assert proposal["behavior_change"] is True
    assert proposal["public_issue"] == "https://github.com/maximalfocus/archsift/issues/125"
    summary = validate_graph_change(proposal, snapshot, base)
    assert summary["changed_entry_count"] == 2
    assert len(snapshot.nodes) == 115
    assert len(snapshot.relations) == 90
    assert "src/archsift/knowledge/*.json text eol=lf" in (
        _REPOSITORY / ".gitattributes"
    ).read_text(encoding="utf-8")


def test_corpus_covers_every_typed_kind_and_keeps_competing_knowledge_visible() -> None:
    snapshot = packaged_corpus_snapshot()

    assert {node.kind for node in snapshot.nodes} == set(NodeKind)
    assert {relation.kind for relation in snapshot.relations} == set(RelationKind)
    assert {node.id for node in snapshot.nodes if node.kind is NodeKind.ARCHITECTURE_CLASS} == {
        "agentic-control",
        "deterministic-automation",
        "fixed-ai-workflow",
        "human-owned-work",
        "process-redesign",
    }
    by_id = {node.id: node for node in snapshot.nodes}
    assert by_id["complexity-implies-runtime-agency"].lifecycle is Lifecycle.CHALLENGED
    assert (
        by_id["runtime-agency-requires-unpredefinable-execution"].lifecycle is Lifecycle.SUPPORTED
    )
    conflict_kinds = {
        relation.kind
        for relation in snapshot.relations
        if relation.object_id == "complexity-implies-runtime-agency"
    }
    assert conflict_kinds == {RelationKind.CHALLENGES, RelationKind.SUPERSEDES}


def test_corpus_sources_exactly_match_the_public_method_registry() -> None:
    snapshot = packaged_corpus_snapshot()
    graph_sources = {
        node.id: node for node in snapshot.nodes if node.kind is NodeKind.EVIDENCE_SOURCE
    }
    method_sources = {source.id: source for source in METHOD_CITATIONS}

    assert set(graph_sources) == set(method_sources)
    for identifier, source in method_sources.items():
        graph_source = graph_sources[identifier]
        assert graph_source.source is not None
        assert graph_source.label == source.title
        assert source.publisher in graph_source.statement
        assert graph_source.source.locator == source.url
        assert graph_source.source.version == source.version_date
        assert graph_source.source.publication_state == "primary publication"
        assert graph_source.citations == ()


def test_every_packaged_rule_has_exact_source_parity_and_a_complete_trace() -> None:
    snapshot = packaged_corpus_snapshot()
    nodes = {node.id: node for node in snapshot.nodes}
    rule_relations = {
        relation.object_id: relation
        for relation in snapshot.relations
        if relation.kind is RelationKind.INFORMS_RULE
    }

    rules = list_rules()
    assert {rule.id for rule in rules} == {
        node.id for node in snapshot.nodes if node.kind is NodeKind.DECISION_RULE
    }
    assert set(rule_relations) == {rule.id for rule in rules}
    for rule in rules:
        graph_rule = nodes[rule.id]
        assert tuple(citation.source_id for citation in graph_rule.citations) == rule.source_ids
        relation = rule_relations[rule.id]
        assert tuple(citation.source_id for citation in relation.citations) == rule.source_ids
        root_id = f"rationale-{rule.rationale_id.split('#', 1)[1]}"
        view = construct_case_view(
            snapshot,
            CaseViewRequest(
                root_ids=(root_id,),
                finding_ids=(rule.id,),
                bindings=(FindingBinding(rule.id, rule.id),),
            ),
        )
        traces = cast(list[JsonObject], view.content["reusable_claim_traces"])
        root_trace = next(trace for trace in traces if trace["claim_id"] == root_id)
        assert root_trace["case_finding_ids"] == [rule.id]
        assert root_trace["rule_paths"] == [[root_id, f"{root_id}-informs-{rule.id}", rule.id]]


def test_synthetic_request_exposes_a_trace_and_conflict() -> None:
    request = json.loads(_REQUEST.read_bytes())
    view = construct_case_view(
        packaged_corpus_snapshot(),
        CaseViewRequest(
            root_ids=tuple(request["root_ids"]),
            finding_ids=tuple(request["finding_ids"]),
            bindings=tuple(
                FindingBinding(item["finding_id"], item["rule_id"]) for item in request["bindings"]
            ),
        ),
    )

    assert view.content["conflict_relation_ids"] == [
        "bounded-agency-theory-supersedes-complexity-theory",
        "fixed-flow-counterexample-challenges-complexity-theory",
    ]
    assert view.content["case_finding_ids"] == ["agentic-agency-fact-non-decisive"]
    assert view.content["finding_relevant_relations"] == [
        {
            "content_identity": next(
                item["content_identity"]
                for item in cast(list[JsonObject], view.content["finding_relevant_relations"])
            ),
            "id": "rationale-agency-necessity-informs-agentic-agency-fact-non-decisive",
        }
    ]


def test_graph_corpus_cli_human_json_quiet_and_no_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["graph-corpus"]) == ExitCode.SUCCESS
    human = capsys.readouterr().out
    assert packaged_corpus_snapshot().graph_version in human
    assert packaged_corpus_snapshot().snapshot_content_identity in human
    assert "115 nodes across 9 kinds; 90 relations across 7 kinds" in human

    assert main(["graph-corpus", "--json"]) == ExitCode.SUCCESS
    assert capsys.readouterr().out.encode("ascii") == packaged_corpus_bytes()

    assert main(["graph-corpus", "--quiet"]) == ExitCode.SUCCESS
    assert capsys.readouterr() == ("", "")
    assert list(tmp_path.iterdir()) == []


def test_packaged_corpus_binding_preserves_the_ordinary_synthetic_assessment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "case"
    shutil.copytree(_REPOSITORY / "examples" / "fixed-workflow", workspace)
    (tmp_path / "snapshot.json").write_bytes(packaged_corpus_bytes())
    (tmp_path / "request.json").write_bytes(_REQUEST.read_bytes())
    monkeypatch.chdir(tmp_path)

    assert main(["assess", "case", "--json"]) == ExitCode.SUCCESS
    baseline = json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                "assess",
                "case",
                "--graph-snapshot",
                "snapshot.json",
                "--graph-request",
                "request.json",
                "--json",
            ]
        )
        == ExitCode.SUCCESS
    )
    graph_record = json.loads(capsys.readouterr().out)

    assert graph_record["assessment"] == baseline["assessment"]
    assert graph_record["graph_use"]["supported_finding_rule_ids"] == [
        "agentic-agency-fact-non-decisive"
    ]
    assert graph_record["graph_use"]["graph_version"] == packaged_corpus_snapshot().graph_version
