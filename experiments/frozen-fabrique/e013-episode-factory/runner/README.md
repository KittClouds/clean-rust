# Bank construction runner

This directory owns orchestration, separate from the reusable factory core and the D/C family libraries.

Required order:

1. Validate the first E013 construction contract and source/template hashes.
2. Materialize and commit the six D and four C Rust repository templates; record real commit and tree identities.
3. Derive private bank/cell/task seeds. Derive one hidden empty-valid ordinal per cell and independent candidate-order seeds.
4. Generate candidate sets and fixtures with family adapters.
5. For each candidate, reset the exact task state, apply the patch, compile, run visible screening, and run hidden completion. Preserve every receipt.
6. Check exact D/C counts and cross-bank disjointness before sealing. Seal C before any D observer outcomes exist; no observer work is authorized here.
7. Run the independent audit and write final immutable roots. A failed gate leaves a preserved construction attempt, not a `READY` bank.

The runner must avoid loading C payloads into any future D development path. This construction program is permitted to audit both banks before either is exposed.
