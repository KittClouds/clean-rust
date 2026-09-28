# E4-0 Ledger scoring adapter candidate v01

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
and gates, single-event binding, escrow/scope/source-path rejection, and a synthetic
eight-endpoint qualification, plus synthetic E3 asset hash and tamper checks. They
touch no actual E4 label/cache, E3 heads,
tokenizer, model, GPU, or Ledger state.
