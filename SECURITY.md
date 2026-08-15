# Security Policy

## Supported versions

ArchSift is pre-alpha. Security fixes are applied to the latest code on the default branch until the first supported release line is declared.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or include private case data in a report.

Use GitHub's private vulnerability reporting:

https://github.com/maximalfocus/archsift/security/advisories/new

Include the affected version or commit, reproduction steps, impact, and any suggested mitigation. Maintainers will acknowledge the report as soon as practicable and coordinate disclosure after a fix is available.

## Data boundary

ArchSift is intended to run locally without telemetry. Case files and evidence are untrusted and may contain confidential information. Never attach real case material to public issues or pull requests.

Registered documents and repository files remain private case material beneath
`evidence/registered/`. Registration copies exact bytes and deliberately never
parses, decodes, decompresses, renders, imports, or executes them. Repository
commit identities are caller-supplied provenance: ArchSift runs no Git command,
hook, discovery, or network request and does not prove a commit-to-file
relationship. Registration rejects links, traversal, special files, changing
sources, and identifier collisions; callers must still protect the workspace
with permissions appropriate to the source material.
