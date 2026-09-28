# E013 construction audit plan v0.1

This is an independent audit plan for the first E013 construction contract. Its gates concern bank construction only. They do not evaluate an E013 observer.

## Mechanical invariants

- Rehash every source, repository snapshot, candidate patch, fixture, receipt, and projection listed by a bank manifest. Reject missing or extra unlisted files in immutable bank roots.
- Require D `(6 repositories, 8 families/repo, 12 episodes/cell, 576 episodes, 48 empty-valid)` and C `(4, 8, 16, 512, 32)` exactly.
- Require unique episode and candidate IDs. Recompute D/C intersections over repo commit, family ID, task identity, task seed, candidate content hash, and fixture content hash. Record each intersection cardinality.
- Reconstruct each episode from only the manifest and frozen repository commit. For every candidate, reset to the task state, apply the patch, compile, run visible checks, then run hidden checks in a separated adjudicator context. Compare all outcomes with the construction receipt. A cache may accelerate repeat runs but must not substitute for cold replay evidence.
- Confirm every offered candidate applies and compiles. A candidate that fails basic patch or compile hygiene is a construction defect, not a wrong-but-legal negative.
- Recompute valid sets from hidden outcomes. Require exactly one zero-valid episode per cell, and at least one valid candidate on every other episode. Do not infer these counts from generator intent.
- Confirm visible and hidden fixture roots are disjoint. Parse observer projections and search serialized bytes for hidden paths, fixture IDs, expected outputs, gold-patch markers, valid-set fields, and construction-only provenance fields.
- Check candidate order is a permutation of stable candidate IDs and was computed from an order seed independent of hidden validity. No candidate ID or public position may encode an answer bit.
- Verify C is sealed before any D observer outcome file exists. Since E013 observer contact is currently closed, the construction receipt should record zero observer invocations.

## Plausibility and difficulty diagnostics

Report distributions by bank/repository/family: candidate count, valid-count, patch byte length, changed-line count, visible pass, hidden pass, provenance class, paired-sibling count, and declared difficulty coordinates. Compare these distributions across valid and invalid candidates. Large perfect separations require review; they are not automatically repaired after observer contact.

For the negative set, distinguish legal compile-pass behavioral failures from visible-pass/hidden-fail near misses. Inspect a predeclared sample of candidate diffs blind to validity, then open labels and record whether style, naming, or formatting revealed the answer. This audit is construction-side and must finish before sealing.

## Provenance and limits

The first contract has no predecessor E013 v0.2. Search for E009/E010/E012 artifacts in the named workspace and record exact search roots, patterns, and results. If those predecessor inventories remain unavailable, report bounded evidence rather than a global disjointness claim.

Record actual Rust toolchain and build target. `G:` was absent at intake on 2026-09-26, so any fallback must be explicit. Keep the source tree and bank outputs separate and preserve all failed construction attempts.
