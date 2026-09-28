# Audit notes — 2026-09-27

## How to read this folder

| File | What it holds |
| --- | --- |
| `THREADS.md` | one row per agent thread: id, location here, counts, sources |
| `sources.tsv` | every source copied from: path, git commit, committed or working-tree state |
| `included.tsv` | every file here: thread, source, original path (git sources add `@blob`), SHA-256 of the source bytes, new path, bucket |
| `excluded.tsv.gz` | everything not copied: original path, file count, bytes, reason, bucket (ARCHIVE stays in place; DISPOSABLE is regenerable) |
| `conflicts.tsv` | paths where two sources disagreed, and how it was resolved |
| `variants/` | the other copy of each real content conflict |
| `inventory.tsv` | worktrees, branches and folders outside this branch, classified for a later cleanup |
| `edits.md` | the only edits made to copied files |

Nothing at any source location was moved, deleted, or modified.

## Selection rule

Copied: source code, manifests, lockfiles, plans, reports, locks and receipts
within size limits (code up to 512 KiB, Markdown up to 1 MiB, other text up to
256 KiB). Inside run folders (`artifacts`, `runs`, `results`, `work`, `logs`,
`qualification`, ...) only code, Markdown up to 256 KiB and JSON, CSV or TSV
summaries up to 32 KiB were copied.

Not copied: binary data, model weights, `.jsonl`/`.rdj` record streams, larger
run outputs, build products (`target`, venvs, `site-packages`, caches), nested
git checkouts and copied third-party repositories (`vendor`, `repositories`,
`tasks`, anatomy snapshots). Kammi ledger stores (`.journal`, `.ledger`, `.lbdb`)
and any file named like a secret (`*.env`, `*.pem`, `*.key`, `secrets.*`,
`credentials.*`, `*.token`, `auth.json`) were not copied; they are listed by
location only.

## Conflicts

- The GLiNER2.5 bridge files differ from the shared checkout only in line endings.
- Nine research files differed in content between the shared checkout and a side
  worktree (FAS-R1 stage-0 worktree, E4-0 contract worktree). The newer copy is
  in place; the other is kept under `variants/`.

## Duplicate worktrees

- `.codex/worktrees/5c65`: its research files match the shared checkout except
  for line endings; its Phoenix and NorthStar edits are older than the product
  branch. Classified REFERENCE; no unique research content.
- `.codex/worktrees/3b32`: 8,306 files identical to the shared checkout; the 5
  research files that differ (FLY-REACH-03 executor, JEV v0.8N generator) are
  older than the shared copies. Classified REFERENCE.

## Credentials

A pattern scan found no keys or tokens. Two Kammi ledger unit tests
(`infrastructure/kammi-ledger/tests/test_memory.py`, `test_vault.py`) contain
short fixed fixture strings used only inside temporary test ledgers; they are
not service credentials. The vault adapter's fixture test reads its token from
the file named by `PHOENIX_VAULT_FIXTURE_TOKEN_FILE`.
