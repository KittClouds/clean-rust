# E013 bank construction handoff to Kinetic Kammi

Date: 2026-09-26. The user redirected the whole E013 bank job to Kinetic Kammi. This file records the live state; it is not a bank seal or readiness receipt.

## Boundary and authoritative protocols

- Isolated worktree: `C:\Users\shuga\.codex\worktrees\e013-episode-factory\clean-rust`, branch `codex/e013-episode-factory`. Preserve it; it contains all current work.
- Actual sealed E013 v0.2 protocol: `C:\rd-c\selective-cognition-action-region-program\experiment-013-trust-signal\E013-TRUST-SIGNAL-DEVELOPMENT-PROTOCOL-v0.2.md`, SHA-256 `840be748b8aed6b9b642c3c622f079a61c847c61d0e5c9842b04a2a229aa6bdc`; lock SHA-256 `9bd4cfeac86e613ddb7f46ef1b4f8ec92d2aedf702b260323822cb3c53e97ba2`.
- Later sealed v0.3 protocol SHA-256 `74910aededa494c49f741a05fa4d632e1f46c8466ae31ac2447f42832f25c70e`; lock SHA-256 `422efcda45938c5aa1258c49afd101ef30fa4f4405ed3b7a70945a4716aec788` at the same directory.
- User explicitly selected the mandated **v0.2** bank counts after discovering v0.3: D 576 = 6×8×12 with 48 empty-valid (one/cell); C 512 = 4×8×16 with 32 empty-valid (one/cell). User then asked to assign a separate subagent to cover v0.3 as well. Keep identities, seeds, artifacts, and claims separate.
- v0.3 instead requires D 864 = 6×8×18 with 48 empty-valid and one truth-changing pair/cell; C 1,120 = 4×8×35 with 64 empty-valid (two/cell) and one pair/cell. Neither protocol authorizes E013 model contact. No bank generation, observer/model contact, T1–T5 scoring, or seal has occurred in this branch.

## Current files and status

- `CONTRACT-v0.1.md` and `contract-v0.1.json` are a **stopped erroneous first draft**: initial search missed `C:\rd-c` and wrongly asserted no predecessor. Preserve for history, do not use as bank authority. `CONSTRUCTION-CORRECTION-v0.2.md` explains this. `contract-v0.2.json` is the provisional implementation contract bound to sealed E013 v0.2.
- `SOURCE-INTAKE-v0.1.md`, `source-intake-v0.1.json`, `FUTURE-BANK-NOTEBOOK-v0.1.md`, and `AUDIT-PLAN-v0.1.md` record primary-source design influence and intended audits. Public benchmark rows/gold patches were not imported.
- Private seeds were generated **before episode generation**: v0.2 C at `D:\codex-runs\e013-episode-factory-v0.2\seeds\C.bin` (SHA-256 `eb21563cb05fd2b396eca1df9a7e81577f2d0f1d5a50e5ddb4d609ee97d9c3ee`), D at sibling `D.bin` (SHA-256 `f20fb209a13c5e8759de0af3d3e4888d354568390650270e99afd52e11f3303d`). `PREGEN-SEED-RECEIPT-v0.2.json` binds them. Older v0.1 seeds are preserved but superseded.
- `factory/` contains provisional Rust core for schema, repository materialization, independent candidate replay, visible/private packaging, and per-episode seals. Recent edits are **unverified**. Known compiler blocker: `package.rs` moves `hidden_record` before later path use. Core tests need new scratch/target/timeout options and smoke patches must target allowed `src/*.rs` paths. `CORE_INTERFACE.md` is missing. Core agent stopped; no complete test pass.
- `families/d/` contains six Rust template roots, catalog, spec/patch drafts, and template materializer. Adapter is incomplete: `src/family.rs` and `src/tests.rs` missing. Latest materializer edit was not rerun. Known D issues: boundary patch renderer uses old signature; pair candidate dedupe can yield <4; some supposed distractors are valid; limits hidden fixtures miss a wraparound case; boundary fixtures need updated arguments. D agent stopped.
- `families/c/` contains four Rust template roots and C spec/provenance/oracle/candidate drafts. Adapter is incomplete: `generate.rs` and `tests.rs` missing. No build run. Per-ordinal task/pool variation and pair behavior remain unresolved; candidate bodies/mutants unverified. C agent stopped.
- `runner/` contains a provisional v0.2 outer runner. It binds actual v0.2 protocol/lock hashes, expects seeded C/D libraries, D scratch/target environment paths, and attempts exact counts/empty slots plus one optional truth-changing pair/cell as a prospective construction extension. It has not compiled or run. Confirm it matches the final core API and seal source inputs before use.
- The primary dirty checkout at `C:\code land\clean-rust` was accidentally touched by three new core scaffold files, then those exact files were copied/hash-verified into the isolated worktree and removed. Primary `git status --short -- experiments/e013-episode-factory/factory` is clean; unrelated primary state was preserved.

## Prior task material and independent audit

Prior E009 and E010 artifacts are at `C:\rd-c\experiment-009` and `C:\rd-c\experiment-010`; E012 is at `C:\rd-c\selective-cognition-action-region-program\experiment-012`. E010 used ripgrep and turbovec; E012 frozen bank reports 48 tasks across three repository IDs. Check actual prior task/source/candidate identities, not only new namespace strings. D/C disjointness and visible/hidden leakage audits are pending.

Core replay must reject any offered candidate that fails source firewall, patch application, or compilation. It must prevent candidate edits to checker/tests/fixtures/Cargo manifest, use bounded timeouts, and record actual scratch/Cargo target paths. `G:` is absent on this host; `D:` is the prior program's build-target volume. Hidden fixtures currently enter a process that links candidate code; fixed candidate patches need strict source/path audit, and this should not be described as a sandbox. Do not claim bank readiness or model authorization until full executable replay, independent audit, and sealing pass.

## Requested next move

Resume in the isolated worktree. Finish and test the shared core and v0.2 D/C adapters on sacrificial cases first. Freeze source/template hashes before generating banks. Build and independently audit C and D under the user-selected v0.2 counts, preserving all failed attempts. Assign a separate GPT-6 Luna extra-high subagent to the v0.3 construction profile and banks under a separate identity. Keep E013 observer contact closed throughout.

`E013_MODEL_CONTACT_AUTHORIZED=false`
