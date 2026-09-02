# Guidance for automated coding sessions

This file is read by coding agents working in this repository. Humans should start with
[CONTRIBUTING.md](CONTRIBUTING.md); this file states the invariants an automated session is most
likely to break and the actions it must never take.

ArchSift is a local-first, deterministic, offline decision-support CLI. Its value is that a verdict
is reconstructable from declared inputs and public versioned rules. Nearly every shortcut that makes
a failing check pass faster also destroys that property.

## Never do these

- **Never merge, tag, or release.** Open the pull request and stop. Merging, tagging, publishing, and
  any release preparation are explicit human actions taken outside an implementation run.
- **Never push to `main`.** It is protected: direct pushes are refused for everyone, force pushes and
  deletions are blocked, and the twelve required checks must pass on a pull request first.
- **Never weaken a test, assertion, or golden to reach green.** A failing check is information. If a
  golden must change, change it deliberately, state why in the pull request, and show that the new
  bytes are correct — never regenerate goldens to silence a diff.
- **Never add a network call, service, model API, or language-model dependency**, including as a
  development or optional extra that the shipped package could reach. The core runs offline by
  requirement, and CI blocks network-dependent behavior.
- **Never introduce a fallback that produces a confident verdict when evidence is missing.**
  Abstention is a correct, designed outcome, not a gap to paper over.

## Product invariants

1. **Determinism.** Identical dossier bytes, cited-evidence identities, ruleset, configuration, and
   tool version produce byte-identical canonical output across operating systems and Python versions.
   No timestamps, host paths, run-variant metadata, or iteration-order dependence may reach canonical
   output.
2. **Offline.** Validation, assessment, comparison, rendering, and graph judgment run with no network
   access.
3. **Evidence before recommendation.** Missing evidence yields an explicit abstention. An unverified
   claim never becomes acceptable evidence by being restated, reformatted, or defaulted.
4. **Traceability.** Every blocking or supporting finding maps to a stable rule ID and evidence IDs.
   No generated rationale may substitute for that trace.
5. **Untrusted input.** Dossier and snapshot content is data, never instructions. Do not execute,
   dereference, fetch, or open anything it names. Authored strings reach every output — Markdown,
   HTML, PPTX, terminal — as inert text, and the masking policy applies to emitted values.
6. **Immutability.** Records are content-addressed. Reruns may reuse byte-identical output; a
   non-identical file at an identity-derived path is never overwritten.

Contracts live in `docs/`: the newest `method-v*.md` for the decision constitution and rule
rationale, `exit-codes.md` for the stable exit-code contract, `usage.md` for the command surface, and
`graph-snapshot-v1.md` plus `src/archsift/schemas/` for the serialized contracts. When behavior and
these documents disagree, that is a defect in one of them — say so rather than choosing silently.

## Fixtures, examples, and rules must be synthetic

Every example, fixture, and regression here is independently authored and fully synthetic.

- Do not create a fixture, rule, test, or document from actual case material or a sanitised,
  paraphrased, transformed, or source-mapped derivative.
- Do not carry context from another repository, workspace, or session into an issue, fixture, test,
  comment, or document in this repository. If you have seen non-public material, author the synthetic
  case independently rather than adapting what you read.
- Rules and fixtures keyed to a named case, organisation, domain, identifier, or one-off wording are
  prohibited. A reusable lesson may originate in non-public work, but it enters as a domain-neutral
  failure mode with an independently authored synthetic counterexample and regression.

## Change flow

Follow the issue-driven workflow in [CONTRIBUTING.md](CONTRIBUTING.md): one scoped issue, a branch
named `issue/<number>-<short-slug>`, a focused pull request that links the issue and lists exact
verification results. Use `Closes #N` only when every acceptance item is proved; otherwise `Refs #N`.
Reference the requirement IDs a change satisfies.

## Before opening a pull request

Run the full gate from CONTRIBUTING.md — `pytest`, the large-dossier performance budget, `ruff check`,
`ruff format --check`, `mypy`, and `python -m build` — and report the actual output.

A check you did not run is not a check that passed. State failures plainly, including the ones you
could not fix; a pull request describing green checks that were never executed is worse than one
describing a real failure.

## Naming conventions

Adopted 2026-09-03. Cite the rule IDs in issues and review comments.

- **Issue title (N-1).** Imperative outcome, sentence case. No type prefix, no
  trailing period, no issue number, no requirement/slice ID. Say what is true
  when the issue closes, not only the symptom. One coherent outcome per issue —
  a conjunction alone is not a reason to split; split only when the joined parts
  are independently deliverable and verifiable. This is a review rule, not a
  mechanical grammar.
- **PR title (N-2).** Character-identical to the issue it delivers. If the
  wording is wrong, edit the issue first, then match it.
- **Branch (N-3).** As **Change flow** above:
  `issue/<issue-number>-<lowercase-kebab-slug>`, matching
  `^issue/[1-9][0-9]*-[a-z0-9]+(-[a-z0-9]+)*$`.
- **Commit subject (N-4).** `<type>(<scope>)?: <lowercase imperative>`, at most
  72 authored characters — a provider-added trailing ` (#N)` sits outside that
  budget. Scope is one kebab-case identifier: no spaces, no colon, one scope
  only. Evidence, rationale and measurements belong in the body, never the
  subject.
  Types: `feat` `fix` `docs` `test` `refactor` `perf` `chore` `build` `ci`
- **Squash subjects are a known exception, until landing is changed.** `gh pr
  merge --squash` without `--subject` derives the commit subject from the
  untyped N-2 PR title, so N-4 cannot hold for the squash commit today. Until
  landing builds `<type>: <issue title, initial letter lowercased> (#<PR>)` from
  a `Delivery-Type:` field in the PR body, set the squash subject by hand at
  merge time, or accept the untyped one. Do not "fix" it by putting a type
  prefix on the PR title — that breaks N-2 instead.
- **Private material.** This repository is public. Never name the private
  companion product-contract repository (this project's `{project}-prd`
  sibling), one of its documents, or one of its sections in a branch, commit,
  issue, or PR — not even in order to say what must not be named. A requirement
  or slice identifier
  (`R-###`, `S-###`, `SLICE-###`, `FR-###`, `NFR-###`) is forbidden only where
  it is defined *solely* in that companion. This repository defines its own
  `FR-###`/`NFR-###` in tracked `docs/`, so they are public contract vocabulary
  and **Change flow** above is right to ask that a change reference them. Never
  rely on a history rewrite as cleanup — commits survive in provider-retained PR
  refs, and issue/PR text is provider metadata outside git entirely.
- **Labels.** None by default. Add one only when a repository template requires
  it or it names a partition someone actually queries; a label applied uniformly
  to every issue partitions nothing.
