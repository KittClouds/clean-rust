# Releasing the Library

The live flight gate is bound to exact source and binary identities (amendment v3), so every
Library change reaches production as a release: evidence, `kammi-ledgerd accept`, and a
restart. `tools/release.py` does all of it.

## Layout (`program-infrastructure/kammi-ledger-rs-operational/`)

```text
release.json               the installed release: commit, source_dir, bin_dir, acceptance
releases/<commit>/
  source/                  byte copy of the tree at <commit>; the daemon hashes THIS
  bin/                     the release's binaries (kammi-ledgerd, projector, migrate, state-dump, kammi, kammi-mcp)
  binaries.json            their SHA-256
  evidence/                what `accept` registered, plus reuse.json when evidence was reused
  release-report.json      every step with timestamps, including downtime
bin/                       the installed copy the service runs
releases.jsonl             release history
```

The daemon's `KAMMI_SOURCE_DIR` is the installed release's `source/` snapshot, never the
working tree. Editing the repository, adding crates or writing docs cannot close the live gate.
Only a release changes what the daemon is bound to.

## Commands

```bash
python tools/release.py plan   # changed hashed files, binary hashes, the tier
python tools/release.py run    # release the committed HEAD to the live Library
```

Run them from the kammi-ledger venv, with `CARGO_TARGET_DIR` set. `run` refuses a dirty tree
and a HEAD that is already installed.

## Evidence tiers

| Tier | When | Evidence |
| --- | --- | --- |
| source-only | `kammi-ledgerd.exe` and `kammi-projector.exe` are byte-identical to the installed release | Behavioural reports (HTTP and memory differential, supervision, clients, stress, shadow, rehearsal) are reused, because identical binaries produced them. `reuse.json` records their source and the binary hashes. Fresh: the full workspace tests, including the 1M JCS oracle and the corpora, plus shell conformance |
| full | Either binary changed | `--evidence-from DIR`: fresh harness reports plus a `binaries.json` proving they came from exactly the staged binaries. Fresh as above |

Every release also produces, at the live head with the daemon stopped, a restore round trip
(`backup-restore.json`) and Python's unmodified `independent_verify` over `export-v1`
(`independent-verify.json`). That audit is valid only while the journal holds v1 vocabulary.
The release that activates amendment v4 must replace it (amendment v4 §6).

## The switch and its fallback

1. Stop the daemon, and wait for the projector by path (never by process name).
2. Verify at head: export, restore check and the independent verifier.
3. `accept` with the staged binary against the staged source snapshot.
4. Install the binaries and `release.json`, then start.
5. Probes: flight `OPEN` under the new acceptance; `kammi status`; `kammi-mcp` tools list;
   the Python CLI; an ordinary `/v1/authorize` (probe records `release-probe-<commit>`, lab
   `kammi-ops`).

Downtime is steps 1-4, measured in `release-report.json`.

If anything fails before step 3, the previous release starts unchanged. If it fails after
acceptance, the previous release is **re-accepted**, because the gate follows the latest
acceptance: its evidence is copied into `evidence-fallback-<utc>`, verified at the new head,
accepted with its own binary and snapshot, installed and started.
