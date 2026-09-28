# E009 decoding amendments v2 and v3

Date: 2026-09-25. These amendments continue run `e009-20260925-pilot-01` in place.

## v2 — output budget

The two initial MiniCPM shadow requests returned HTTP 200 but exhausted the frozen 128-token completion cap with empty final content. Their request and response records remain under `shadow-small/`; they are preserved as interface diagnostics and excluded from all predictions and scores. No lane actions or task scores were produced from them.

Set `maximum_output_tokens` to 1024 for both local observers. The model artifacts, runtimes, system prompt, task frames, option order, labels, input normalization, thresholds, routing, temperature, top-p, and seed stay fixed. The small observer still runs before the large observer, and all model output remains proposal-only.

The two 1024-token shadow retries are preserved under `shadow-small-1024/` and excluded: both used the full completion budget in `reasoning_content`, returned empty final `content`, and ended with `finish_reason=length`. This showed that the output cap alone did not fix the interface failure.

## v3 — reasoning mode

The local runtime log and response metadata identify the cause: automatic template reasoning consumed every completion token before final JSON. The installed llama-server exposes `--reasoning off` to disable that mode. Apply that server option to both observer endpoints and keep the 1024-token output cap.

No model artifact, prompt, schema, task frame, action option, label, normalization, threshold, routing rule, temperature, top-p, or seed changes. Every request records the active runtime mode. Both failed attempt sets remain intact and excluded; the corrected shadow requests and all paired lanes run inside the same pilot-01 directory.

The original `frozen-input-lock.json` remains unchanged and records the pre-contact 128-token configuration. The existing bundle manifest is amended in place, preserving bundle IDs and every field other than the output cap. The original pre-contact bundle manifest and runner remain archived under `protocol-source/`.
