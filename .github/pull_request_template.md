## Summary

<!-- Describe the issue-focused change. -->

## Linked issue

Closes #

## Acceptance evidence

- [ ] Every issue acceptance item maps to a change, test, or explicit evidence.
- [ ] Evidence is independently authored synthetic material; no actual case material or sanitised, paraphrased, transformed, or source-mapped derivative is included; no credentials, internal URLs, or proprietary policy text.
- [ ] The diff contains no unrelated cleanup or generated build output.

## Knowledge graph gate (when applicable)

- [ ] A graph-change issue names the reusable failure mode, public evidence, stable-ID impact, and expected behavior effect.
- [ ] The canonical proposal validates against the exact base/proposed snapshots and accounts for every semantic delta.
- [ ] Changed asserted entries cite the proposal's public evidence sources; challenge, supersession, deprecation, and removal remain explicit.
- [ ] Any behavior change names independently authored synthetic counterexample and regression-test IDs; graph nodes, relations, citations, fixtures, and source mappings are not case-derived.
- [ ] The proposal attests that open-world absence is not evidence of nonexistence.

## Verification

```text
python -m pytest
python -m benchmarks.large_dossier --max-seconds 2.0
python -m ruff check .
python -m ruff format --check .
python -m mypy src benchmarks tests/test_performance.py
python -m build
```

## Risks and excluded follow-ups

<!-- Name excluded follow-ups or write "None". -->
