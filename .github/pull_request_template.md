## Summary

<!-- Describe the issue-focused change. -->

## Linked issue

Closes #

## Acceptance evidence

- [ ] Every issue acceptance item maps to a change, test, or explicit evidence.
- [ ] Evidence is independently authored synthetic material; no actual case material or sanitised, paraphrased, transformed, or source-mapped derivative is included; no credentials, internal URLs, or proprietary policy text.
- [ ] The diff contains no unrelated cleanup or generated build output.

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
