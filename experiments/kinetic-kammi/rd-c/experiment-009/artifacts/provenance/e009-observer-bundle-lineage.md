# E009 observer bundle lineage correction

Date: 2026-09-25

This is a provenance repair. The E009 pilot request and response records, the failed attempts, and the pilot scores remain byte-for-byte unchanged.

## Identities

| Identity | Effective contract | Status |
| --- | --- | --- |
| `minicpm5-2b-q8-local-v1`, `ternary-bonsai-2-27b-ptq1-local-v1` | 128 output tokens; original prompt, schema, template, and 700/600 thresholds | Restored to the exact pre-contact bundle lock. Its SHA-256 is `e3a719ac2644ec6dfde0c45e6820cc7f4c4a567e7d003196b46df355f3cac2bf`. The 128-token empty-output attempts remain in pilot-01. |
| `minicpm5-2b-q8-local-v2`, `ternary-bonsai-2-27b-ptq1-local-v2` | 1024 output tokens; automatic template reasoning; original prompt, schema, template, and 700/600 thresholds | Reconstructed as the identity for the preserved 1024-token attempts that exhausted output in `reasoning_content`. The original records still contain their historical v1 bundle label. They have not been edited or rescored. |
| `minicpm5-2b-q8-local-v3-calibration`, `ternary-bonsai-2-27b-ptq1-local-v3-calibration` | 1024 output tokens; reasoning off; captured model template, prompt, schema, baseline 700/600 thresholds | Development-only calibration identity. Each manifest hashes the effective runtime settings and templates. |
| `minicpm5-2b-q8-local-v3`, `ternary-bonsai-2-27b-ptq1-local-v3` | 1024 output tokens; reasoning off; captured model template, prompt, schema, development-selected thresholds | Final corrected identity for the held-out run. The selected thresholds are fields in the hashed bundle manifests. |

The restored v1 input and lock match the pilot's archived pre-contact bytes. The 1024-token copies that were temporarily labeled v1 are preserved at `artifacts/provenance/e009-observer-bundle-lineage/root-lock-before-correction-bundle-id-v1-1024.json` and `root-input-before-correction-bundle-id-v1-1024.json`; the attempt output files retain their original hashes. The machine-checkable byte comparison is `models/bundle-lineage/v1-byte-identity-check.json`.

## Evidence boundaries

- The 128-token attempt records remain under `artifacts/runs/e009-20260925-pilot-01/shadow-small/`.
- The automatic-reasoning 1024-token attempt records remain under `artifacts/runs/e009-20260925-pilot-01/shadow-small-1024/`.
- The corrected reasoning-off pilot records and all pilot lane scores remain under pilot-01 as scored. Their score files were not rewritten.
- `models/bundle-lineage/v2-attempt-reconstruction/` is an explicit reconstruction from the preserved effective settings; it does not claim that the pilot request carried the v2 ID at the time.
- `models/bundle-lineage/v3-calibration/` and `v3-final/` bind the runtime mode, captured chat-template hash, output cap, prompt hash, output schema hash, and threshold pair into each BLAKE3 bundle identity.

This correction changes engineering provenance only. It contributes no upstream scientific evidence.
