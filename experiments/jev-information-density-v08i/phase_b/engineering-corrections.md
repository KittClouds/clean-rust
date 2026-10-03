# Phase-B implementation correction log

## 2026-09-21 — Correct two copied SHA-256 values before preflight

The initial, unsealed Phase-B contract contained transcription errors in the
v0.7 feature-manifest digest and the LFM `special_tokens_map.json` digest.
Read-only recomputation against the pinned files produced:

```text
v07 feature manifest
  prior: 1ad6b2df5932dbcded307d8c91a25c6cf2246a75018bf575225849732aad70885
  actual: 1ad6b2df5932dbcde307d8c91a25c6cf2246a75018bf575225849732aad70885

special_tokens_map.json
  prior: 742aefe2b7dec496e8caffdb03a75d0c1a9925d53bd3f3e0d388c96b591b6f4
  actual: 742aefe2b7dec496e8caffdba03a75d0c1a9925d53bd3f3e0d388c96b591b6f4
```

Both corrected digests were then independently checked with PowerShell
`Get-FileHash -Algorithm SHA256`. All other declared reference/model digests
checked in the same read-only audit matched. The first preflight failed closed
on the first typo and created no Phase-B run directory or authorization
receipt. No model was loaded and no data/model computation occurred.

Semantic impact: none. This correction makes the new Phase-B contract point to
the exact already-authorized reference artifacts; it does not change the
model, data, loss, training recipe, evaluation, thresholds, or boundaries.

The preflight will bind the corrected contract hash and current source hashes.
