# E004 run history

- `e004-1790274306797613300`: completed an initial 2,048-task sweep. Superseded after report timing precision and the label-generation boundary were tightened.
- `e004-1790274789302722900`: completed a second 2,048-task sweep with public plans written before separate label generation. Superseded after a test-driven `RunSpec` API cleanup and trace addition for witness source IDs.
- `e004-1790275031951709800`: final 2,048-task paired sweep. Its manifest fingerprints the tested source. This run backs `artifacts/benchmark-report.md`.

All runs remain intact with their own report, trace, plans, input/label files, task journals, action ledgers, and BLAKE3 manifest. The final result does not rewrite the earlier attempts.
