# E4-0 Ledger scoring worker candidate v02

Status: candidate only; not sealed, not authorized, and not run on E4 truth.

This adapter preserves E4-0 v16-v09 gates and imports immutable v04 scorer math
only after checking its exact hash and length. It is a Ledger worker consumer,
not a Ledger client: it cannot issue grants, open panels, create leases, retrieve
protected artifacts, or create authority.

Before prediction preparation, the worker handoff must already validate the
authorized scoring grant. The adapter then verifies the feature cache and row
manifest identities and all twenty E3 head/scaler files against their sealed
SHA-256 and byte lengths. Prediction preparation is CPU-only; it rejects a
process where CUDA has already been initialized. The expected Python, NumPy,
and PyTorch versions are pinned to the E3 scoring runtime.

The population seal metadata identifies primary artifact E4_PRIMARY_TERMINAL_LABELS_V01
at labels/primary-terminal-labels-v01.jsonl, 39,363,264 bytes, SHA-256
225787239ffb3d3920e2c299f0f05cdb59df88a89ddc11ed22edde9ac312a365, 74,668 rows.
Prep used metadata only; the label file was not read, hashed, copied, parsed, or opened.

An authorized Chief/Kammi actor performs the one `open_panel` call for the
Ledger-resolved panel ID, using purpose terminal and the granted run, stage,
actor, authorization, and request IDs. The actor streams the returned bytes
into the fresh stage attempt root and verifies the exposure event and declared
source identity. Only then does Library launch the fenced local worker with
that staged file in `source_files`; the worker does not call `open_panel` and
receives no protected source path. The worker consumes the staged file at
`ledger-inputs/primary-panel-e4-v01.jsonl` and maps the response to the pinned
handoff fields: panel ID, event ID, artifact ID, purpose, run/stage, population
root, SHA-256, byte length, row count, one open event, zero escrow opens, and
the materialized relative path. The adapter checks the identity and bytes.
Retries may reuse the same request ID only for the same idempotent intent. It
must never receive or direct-read the original protected source path or request
either escrow panel.

The frozen score is unchanged: five read-only E3 v02 heads; eight endpoints in
contract order; balanced accuracy; 200 rows/class; 10,000 whole-quartet,
class-stratified replicates; NumPy PCG64 seed 2026092604; one RNG consumed in
endpoint order; linear quantile alpha 0.00625; each lower bound at least 0.90;
all-eight conjunction.

Rows use a 382,300,160-byte per-file cap. Non-row persistent outputs share the
contract's 536,870,912-byte aggregate cap; future worker request must set smaller
individual limits. These are caps, not predicted sizes. Feature cache is upstream
and is not copied into scoring outputs.

| Artifact ID | Cap | Contents |
| --- | ---: | --- |
| E4_SCORING_PREDICTIONS_V01 | 382,300,160 | Primary predictions, no truth |
| E4_SCORING_SCORED_ROWS_V01 | 382,300,160 | Primary labels and predictions |
| E4_SCORING_METRICS_V01 | aggregate cap | Eight metrics and disposition |
| E4_SCORING_BOOTSTRAP_V01 | aggregate cap | 8 x 10,000 float64 values |
| E4_SCORING_LABEL_OPEN_RECEIPT_V01 | aggregate cap | Primary identity and exposure event |
| E4_SCORING_TERMINAL_RECEIPT_V01 | aggregate cap | Grant, roots, disposition |
| E4_SCORING_STAGE_SEAL_V01 | aggregate cap | Non-recursive seal |

The tests use synthetic primary records in temporary files. They check source hash
and gates, single-event binding, escrow/scope/source-path rejection, partial receipt
preservation, the fixed runtime handoff paths, manifest hash/parse behavior, and a
synthetic eight-endpoint qualification with output sealing. They touch no actual E4
label/cache, E3 head payload, tokenizer, model, GPU, or Ledger state.

## Runnable worker and native local-execution spec

`run_scoring.py` is the process entrypoint. Its seven normal files match the exact
`expected_outputs` list in the native `KAMMI_LOCAL_EXECUTION_V1` candidate. KAMMI
uses `max_output_bytes=382300160` as a per-file limit; the worker separately checks
the 536,870,912-byte aggregate cap for non-row persistent outputs. The worker also
requires a fresh output root, applies the frozen 10% D: free-space reserve, records
Windows process peak working set, and rejects a peak above 25,769,803,776 bytes.

The command is an argv array, with no shell:

```text
C:\Users\shuga\AppData\Local\Programs\Python\Python313\python.exe
<candidate-root>\run_scoring.py
--invocation <attempt-root>\ledger-inputs\scoring-invocation-v01.json
--delivery <attempt-root>\ledger-inputs\panel-delivery-v01.json
--panel-file <attempt-root>\ledger-inputs\primary-panel-e4-v01.jsonl
--feature-cache D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-ledger-run-v02\features\V1_FINAL_POSITION.f32le
--row-manifest D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-ledger-run-v02\features\population-row-manifest-v01.jsonl
--e3-head-root D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v02
--output-root D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-scoring-output-v01
```

The attempt root is `D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-scoring-input-v01` for this candidate. The invocation and delivery JSON files are dynamic Ledger/Chief handoffs: their paths are fixed and checked under that root, but their bytes are created after authorization/exposure and therefore are not prebound in `source_files`. Chief must register and audit their hashes after creation. The staged primary panel is listed in `source_files` at its fixed path and is bound to the sealed population hash and length. The original protected label source path is never passed to the worker.

The static native source inventory binds the Python executable and its DLLs, candidate runner/adapter, frozen scorer and writer, E4/E3 contract and seal metadata, feature cache and row manifest, all 20 E3 head/scaler payloads, and the staged panel. The runner checks Python/NumPy/PyTorch versions before feature prediction, checks the frozen scorer and writer file identities, and checks all E3/cache/manifest/panel identities. The Python runtime is CPU-only for this stage; `torch.cuda.is_initialized()` is checked and must remain false.

Input-byte reads have distinct owners. Chief streams and verifies the source panel while satisfying the Ledger exposure. KAMMI verifies each declared `source_files` digest before launch. The scorer then hashes and parses the materialized panel in one open; it separately hashes the feature cache and hashes/parses the row manifest in one sequential pass before inference. These are integrity checks by different components, not a claim that each physical file is read only once end to end.

The bounded executor candidate sets `timeout_seconds=7200` and `poll_seconds=5`. These values are execution-supervisor limits only; they confer no scoring authority. Expected output paths are:

```text
score/predictions-v01.jsonl
score/scored-rows-v01.jsonl
score/metrics-v01.json
score/bootstrap-v01.npz
score/label-open-receipt-v01.json
score/terminal-receipt-v01.json
score/stage-seal-v01.json
```

The v02 packet remains a candidate. Panel exposure, scoring grant, real-label
opening, real predictions, and real scoring are all still false.
