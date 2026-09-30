# LFM2.5-230M specialization atlas

Two independent engineering arms ask how external task specialization moves the frozen BANK-v1 capability map:

* **GLiClass logic:** schema-conditioned multi-label decisions.
* **OpenNER English:** token-level entity extraction using OpenNER's standardized BIO tags.

The arms remain separate. Neither trains on BANK-v1. BANK-v1 is used only after each external-task checkpoint to measure old-observer coordinate survival and refitted-observer information survival. No retrieval, lexical authority, or serving behavior is changed.

## Sources and handling

Source dataset revisions are pinned in `source-lock.json` after preparation. Downloaded parquet and generated training JSONL stay under `D:\phoenix-target-overgraph\lfm-230m-specialization-atlas-20260929\datasets`, outside Git. The model is the local pinned `lfm2.5-230m-base-9d2be55` checkpoint. OpenNER's collection is CC-BY-4.0, with individual source licenses; this run does not redistribute corpus files. GLiClass-v3-logic is Apache-2.0.

OpenNER is limited to the English Tweebank, UNER English EWT, and WNUT17 configurations. Their upstream train/dev/test partitions are preserved and source identity remains on every row. GLiClass is train-only upstream; rows are assigned deterministically to 80/10/10 train/dev/test groups using the source row ID. Candidate labels from one passage never cross partitions.

## Task interfaces

GLiClass is rendered as a passage plus a shuffled list of candidate labels. The model scores each candidate at its own final label token; all supplied true labels are positive and the other supplied labels are negative. This is schema-conditioned classification, not generated free-form prose.

OpenNER is rendered as an instruction, the entity-type schema observed in OpenNER TRAIN only, and the original pretokenized sentence. A token head predicts the standardized BIO tag for each word's first subtoken. Source-native development and test partitions remain separate in evaluation.

Both arms start from the same base model and use their own task head, input formatting, optimizer run, checkpoints, and data. No rows are concatenated across arms. The first engineering pass uses full-backbone fine-tuning with a frozen-base task-head baseline available as a command-line mode. Checkpoints are planned at steps 0, 250, 500, 1000, 2000, and final when those steps are reached.

## BANK-v1 atlas

The four reference surfaces are `middle_plus_final`, `final_plus_mean`, `layer_m4_final`, and `full_mean`. For each specialized checkpoint and surface, report:

* **old observer:** original scaler and linear weights unchanged (coordinate survival)
* **refit observer:** same BANK TRAIN rows and labels fit a new scaler/linear observer (information survival)

BANK examples never update either specialist backbone. Refitting a diagnostic observer on BANK TRAIN is part of the measurement step and does not enter external-task training. TEST truth is joined only after all corresponding BANK predictions are sealed.

## Running

The source parquet used in this execution is under the experiment's `datasets` directory on D:. `pyarrow` is isolated there and added through `PYTHONPATH`.

```powershell
$root = 'D:\phoenix-target-overgraph\lfm-230m-specialization-atlas-20260929'
$env:PYTHONPATH = "$root\runtime-deps"
python experiments/lfm-230m-specialization-atlas-20260929/prepare_sources.py `
  --data-root "$root\datasets" --output "$root\prepared"
```

Training and checkpoint-atlas commands are recorded in the generated run manifest once the data schema smoke checks pass.
