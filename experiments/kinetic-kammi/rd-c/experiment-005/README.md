# R&D-C Experiment 005 — Value of Information

Experiment 005 asks whether an inspection call can improve the answer after it detects a possible problem. It adds a second evidence source that is absent from the public observation frame.

## Run

The experiment source lives on `C:`. Build artifacts use the `D:\cargo-targets\rd-c-experiment-005` target directory.

```powershell
cargo test --manifest-path C:\rd-c\experiment-005\Cargo.toml --target-dir C:\rd-c\experiment-005\target
cargo run --release --manifest-path C:\rd-c\experiment-005\Cargo.toml --target-dir C:\rd-c\experiment-005\target --bin rdc005-bench
```

`target` is a directory junction to the `D:` build directory. A run writes immutable inputs, source-state fixtures, labels, routing plans, E002 task journals, action ledgers, query receipts, a report, and a manifest under `artifacts/runs/e005-<timestamp>`.

## Compared lanes

- `e004_combined`: exact E004 combined route plan and the E004 frame-only resolver. It makes the same paid inspection call and receipts its result, then ignores the new payload as a control.
- `development_voi`: ranks public frames with a domain-level estimate of net benefit fitted on the disjoint development bank.
- `matched_random`: seeded BLAKE3 ranking, at the same exact query and resolver budgets.
- `offline_oracle`: after held-out labels are written, ranks each possible call by its observed correction-minus-harm. It is a non-deployable ceiling.

Every selected episode causes one query and one resolver call. Every resolver proposal still passes through the same compiled E002 authority, simulator, journal, and replay. The inspection result contains an action recommendation, evidence-family key, confidence, signature result, and payload digest. It contains no evaluation label or revision.

## Workload

The held-out and development banks each contain 256 episodes across eight strata. `fresh_consistent_wrong` episodes have agreeing observers, age zero, no warning, and source recommendations consistent with the source-reported revision. The independent inspection fixture fixes 24 of 32 such recommendations and repeats the wrong action on the other eight. `inspection_harm` episodes have a correct active action and a signed, high-confidence wrong inspection result.

The synthetic fixture is a routing and runtime contract test. It does not estimate the quality or cost of a real inspection service.
