# CF-01 preflight blocker

**Status:** `BLOCKED_SOURCE_PROVENANCE`  
**Date:** 2026-09-21  
**Scope:** preflight only; no CF-01 task family or measurements generated.

## Isolation and boundary

- Isolated worktree: `C:\Users\shuga\.codex\worktrees\8b03\clean-rust`
- At inspection: detached `HEAD` `e5a84994da6011605b11e7b89459fa73f7e47570`, clean status.
- Shared checkout `C:\code land\clean-rust` was read only. It is heavily dirty; no files there were changed.
- This packet is the only file written in the isolated worktree for CF-01. No run/output directory was created.

## Candidate examined

The latest dynamic learner candidate I could identify is `experiments/drosophila-heresy/dh08a` in the shared checkout. Later Q09-LFA and Q10 folders are engineering geometry/linearity audits rather than a newer ordinary training runner.

Its `QUALIFICATION.json` reports 56 Rust tests passed, 0 failed, 9 ignored; release build passed; Clippy had 0 warnings; 9 analysis tests passed; and the seed-9100 qualification smoke passed without using fresh measured seeds. The local logs contain those results. However, the qualification manifest does not bind these checks to a source hash.

The associated DH-08A run seal is `experiments/drosophila-heresy/dh08a/artifacts/runs/20260916T054825Z/seal.json`. Its recorded source fingerprints disagree with both `dh08a/src` and the run's `sealed/src` snapshot. The files checked under `sealed/src` currently match the mutable `dh08a/src` files, but not the hashes recorded in `seal.json`. This is a provenance/integrity mismatch; it does not establish that the current source is invalid, but the recorded seal cannot establish its identity.

| File | SHA-256 in run seal | Current `dh08a` SHA-256 |
|---|---|---|
| `src/graph.rs` | `a697285a9fe4560fce32afb5330358ede1c84e96365c23ac96c24d97fe667464` | `23528d6a0e0a76152f77395be638378e23b780e2193200b695b50ba455a40e9d` |
| `src/plasticity.rs` | `d08e4057234dfbd6c4c11da660031263aeaa0327a86b68f7cae04cdc4bf9438c` | `7930f199f57278cb64ea778a9138b072949814e389589439081ffa219ed40d6a` |
| `src/rng.rs` | `794d04a94d011ece9f5758ad05a680b3acccbc82e94e33f4d9a9179c882dd950` | `e0d9267515c7c636c85d8ec1ac20d5673c5588400c2c9fb4d04950c995686d1c` |
| `src/task.rs` | `06b4ea25e3c8c4a0106337866c714c6d74e6d1c0377ac0a934c33e859a02dc61` | `93ec51f1357681941927e8f3625d239e629971d4ba5a8653f8499e8d8f195758` |
| `src/simulation.rs` | `93698d2f1b9c470eed487a615b813eb25c7a5447c3b73d5225dee439a49a7976` | `69c74ab69600ea4d9237315a352e7b655ef352feb9e1b798a712221493f15143` |
| `Cargo.toml` | `dc05c404f9f37e02928af25d0689f0b6b64d6e1b9afe41c7b62595a513157375` | `0e665356fae93ae8a4d664342fe09e375abc827af01dbcd1d1c1010395be4e0b` |

The preflight also found 26 mismatches across the seal's source, manifest, config, protocol, and qualification fingerprints. The current 24-file learner source/dependency snapshot (`src/**/*.rs`, `Cargo.toml`, `Cargo.lock`) has review digest `506097706f4d484251127a3ddf759454cd309f52f37d08bb7228d9a2d47480e9`; this digest is not represented as historically validated. It was computed by hashing UTF-8 bytes of each source file's Windows-relative path, newline, lowercase file SHA-256, newline (source files sorted by full path, then `Cargo.toml`, then `Cargo.lock`), and SHA-256 hashing the concatenation.

## Gate decision

The attached directive says to stop if the latest validated learner and its provenance cannot be established. That condition is met. I did not create `CF-01-CONTRACT.json` or `CF-01-PREEXECUTION.json`, because either would falsely imply that the learner identity had been frozen. I did not copy, repair, or reseal the DH-08A source or artifacts, and I did not inspect the authoritative fly-science hypothesis ledger.

No seed family was generated, no CF-01 training/evaluation ran, and no measurement was started. I did not run builds or tests; the validation evidence above is from existing receipts/logs only.

## Supervisor decision required

Please resolve the source identity before CF-01 freeze: provide or identify an independently validated clean learner snapshot, or authorize a new isolated engineering qualification of a specified source snapshot with source hashes recorded. Until that provenance gate is cleared and the contract/preexecution packet is reviewed, CF-01 remains stopped before task generation and measurement.
