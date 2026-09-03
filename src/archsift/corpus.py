"""The current immutable, evidence-backed architecture knowledge corpus."""

from __future__ import annotations

from functools import cache
from importlib.resources import files

from archsift.graph_change import load_graph_change_proposal, validate_graph_change
from archsift.knowledge_graph import Snapshot, load_snapshot

CORPUS_BASE_SNAPSHOT_RESOURCE = "knowledge/architecture-v3.json"
CORPUS_SNAPSHOT_RESOURCE = "knowledge/architecture-v4.json"
CORPUS_PROPOSAL_RESOURCE = "knowledge/architecture-v4.change.json"


@cache
def _validated_corpus() -> tuple[bytes, Snapshot]:
    """Load both packaged artifacts and enforce their publication contract."""
    package = files("archsift")
    content = package.joinpath(CORPUS_SNAPSHOT_RESOURCE).read_bytes()
    base_content = package.joinpath(CORPUS_BASE_SNAPSHOT_RESOURCE).read_bytes()
    proposal_content = package.joinpath(CORPUS_PROPOSAL_RESOURCE).read_bytes()
    snapshot = load_snapshot(content)
    base_snapshot = load_snapshot(base_content)
    proposal = load_graph_change_proposal(proposal_content)
    validate_graph_change(proposal, snapshot, base_snapshot)
    return content, snapshot


def packaged_corpus_bytes() -> bytes:
    """Return the exact canonical bytes of the current public corpus."""
    return _validated_corpus()[0]


def packaged_corpus_snapshot() -> Snapshot:
    """Return the validated immutable current public corpus snapshot."""
    return _validated_corpus()[1]
