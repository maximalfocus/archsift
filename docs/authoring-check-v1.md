# Simulated assisted-authoring check — protocol 1.0.0

This protocol freezes an independent, fully synthetic check of whether agent products can use
ArchSift's public authoring surfaces to produce and assess a structurally valid decision dossier.
It does not measure human usability, decision quality in a real organisation, or the truth of an
architecture recommendation. At publication of this protocol, no cohort has been run and no
success claim is made.

## Frozen criterion

Run exactly four fresh sessions using four distinct agent products. Each session starts in a fresh
environment, receives only the instructions and synthetic material named below, and binds to the
same full 40-character commit of ArchSift on which this protocol and material set have landed. The
criterion is met when at least three of the four sessions complete every objective milestone with
no maintainer intervention.

A failed or interrupted session remains failed. Do not repair, rerun, replace, or selectively omit
a completed session. A later attempt is a new precommitted four-session cohort and a new result
record.

## Frozen material

The only source material is the packaged `authoring-material/` set:

- `brief.md`: a fictional ParcelPilot routing decision brief;
- `repository/required_fields.py`: inert illustrative source text;
- `repository/routing_rules.py`: inert illustrative source text; and
- `manifest-v1.json`: byte lengths, SHA-256 content identities, a synthetic repository commit, and
  the canonical material-set identity.

The repository snippets are data for `register-repository`; they are not an executable project.
They contain no completed dossier, expected verdict, answer key, or reference output. Sessions
must not receive any private case, real repository, personal data, previous result, transcript, or
maintainer-authored dossier.

## Session instructions

Give every agent product these instructions, without product-specific hints:

1. Work offline in a fresh temporary directory with ArchSift installed from the cohort's bound
   source checkout or built wheel. Do not inspect other workspaces or use network access.
2. Read `authoring-material/brief.md` and `authoring-material/manifest-v1.json`. Treat every fact
   not stated by the material as an assumption, estimate, missing item, or unknown. Never invent an
   observation or artefact.
3. Run `archsift init synthetic-routing`.
4. Register the brief with `archsift register-document`, and register exactly the two repository
   files with `archsift register-repository` using the full synthetic commit identity in the
   manifest. Registration is inert: do not run or import the snippets.
5. Inspect the complete schema-version-3 authoring contract with
   `archsift dossier-schema --schema-version 3 --json`.
6. Author `synthetic-routing/case.yaml` from the frozen material. Cite registrations only where
   the dossier schema permits them and preserve the stated evidence authorship and attestation
   boundary.
7. Run `archsift prerequisites synthetic-routing --json` and complete every prerequisite that
   the synthetic material supports. Leave unsupported facts explicitly missing or unknown.
8. Run `archsift validate synthetic-routing` and then `archsift assess synthetic-routing`.
9. Stop. Report only milestone exit outcomes to the cohort harness. Do not return dossier text,
   reports, decision-record bytes, paths, prompts, or transcripts.

The harness may supply the installed executable path, frozen material path, temporary workspace,
and these instructions. Any additional advice, correction, command, file edit, retry after a
milestone failure, or interpretation from a maintainer is intervention and makes that session
fail.

## Objective milestones

Each session records exactly these six milestones:

- `register_material`: both registrations return exit `0` and bind the manifest identities;
- `inspect_schema`: schema version 3 is emitted successfully before dossier authoring completes;
- `author_dossier`: one schema-version-3 dossier is written without a supplied answer key;
- `complete_prerequisites`: the command runs successfully and the agent responds to its worklist;
- `validate`: final validation returns exit `0`; and
- `assess`: final assessment returns exit `0` and creates the canonical outputs.

A session passes only if every milestone is `pass` and `maintainer_intervention` is `false`.
Milestone assessment is mechanical from command outcomes and file existence; it does not score the
recommendation or authored prose.

## Privacy-bounded result

Record only the fields allowed by
`src/archsift/schemas/authoring-results-v1.schema.json`: pseudonymous session ID, public agent
product/model and harness version, coarse operating-system/Python/install-mode metadata, six
milestone outcomes, intervention flag, derived session result, and a short non-sensitive failure
reason. The cohort record also binds the exact ArchSift source commit and frozen material-set
identity.

Never commit prompts, transcripts, generated dossiers, workspaces, command output, absolute paths,
user or account names, machine identifiers, credentials, real organisation data, or personal data.
Delete temporary session workspaces after extracting the bounded fields. The strict schema rejects
all extra fields and limits every retained string.

## Offline validation

Place the completed record at `authoring-results.json` beneath the current directory and run:

```console
archsift authoring-results authoring-results.json
```

The validator performs no network access and writes nothing. A conforming record with three or
four passing sessions exits `0` with `criterion-met`. A valid record below threshold exits `12`
with `criterion-not-met`. Malformed JSON exits `10`, unsupported schema/protocol versions exit
`11`, contract or consistency failures exit `12`, unsafe paths exit `13`, and unavailable files
exit `14`. `--json` emits a stable machine-readable summary; `--quiet` emits nothing.
