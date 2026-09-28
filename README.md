# Phoenix freeze — 2026-09-27

This branch is a clean, dated snapshot of the Phoenix product plus the agents'
research. It has no history of its own. Every file records where it came from
in `archive-manifest/`. Nothing was moved or deleted at its source: the shared
checkout, worktrees, `C:\rd-c`, and the D: product repositories are unchanged.

```
crates/              Phoenix product crates (Cargo workspace root is this directory)
apps/                Phoenix apps; apps/analysis-bridge is the GLiNER2.5 analysis bridge (own workspace)
vendor/              vendored dependencies the product builds against (velotype, kammi-client)
infrastructure/      Kammi Library service (kammi-ledger) and lab governance — Chief Kammi
experiments/<thread>/  research, one folder per agent thread (see archive-manifest/THREADS.md)
tools/               product scripts (formerly scripts/)
docs/                product docs; docs/jev and docs/lab hold research-wide notes
archive-manifest/    lineage: sources, per-file identity, excluded data, conflicts
memory-lock/, release-lock/  product qualification locks (unchanged from the product tree)
```

## What was included

- **Product:** `KittClouds/phoenix-native` branch `codex/phoenix-graph-gate3b-20260924`
  at the commit listed in `archive-manifest/sources.tsv`, plus the uncommitted
  Phoenix Vault adapter (`crates/phoenix-vault-adapter`, `vendor/kammi-client-0.1.0`,
  `vendor/SDK-HANDOFF-v1.json`, the adapter plan).
- **Analysis bridge:** `clean-rust` branch `codex/phoenix-product-gliner25-bridge-20260923`,
  reduced to the crates `phoenix-analysis-bridge` needs.
- **Research:** source, reports, plans, locks and small evidence from each thread.

## What was left where it is

Generated outputs, model weights, run artifacts, copied third-party
repositories, build products and virtual environments were not copied. Each one
is listed in `archive-manifest/excluded.tsv.gz` with its original path, size,
reason and bucket:

| Bucket | Meaning |
| --- | --- |
| ACTIVE | in this branch |
| REFERENCE | superseded but useful; reachable by the commit or path recorded |
| ARCHIVE | completed-run data kept at its original location |
| DISPOSABLE | regenerable (build output, venvs, caches) |

Included files carry their source SHA-256 in `archive-manifest/included.tsv`
(git sources also record the blob id). Line endings may be normalized on commit,
so compare against the recorded SHA-256 of the source bytes, not the blob here.

## Building

The product workspace builds from the repository root as before. The analysis
bridge is a separate workspace: `cargo build --release -p phoenix-analysis-bridge`
from `apps/analysis-bridge/phoenix`. Experiments keep their own workspaces and
are excluded from the root workspace.

Credentials are never stored here. The vault adapter's fixture test reads its
service token from the file named by `PHOENIX_VAULT_FIXTURE_TOKEN_FILE`.
