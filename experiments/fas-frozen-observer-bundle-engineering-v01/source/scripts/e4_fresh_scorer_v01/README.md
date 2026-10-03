# E4-0 Fresh Scorer v01

This source unit runs the five already-frozen E3 v02 linear observers over
primary E4 feature rows, then scores the eight frozen endpoints once against
the primary terminal labels. It does not fit, tune, or alter an observer.

## Bound input rules

- The E4 manifest is the full ordered manifest. The row_index must be contiguous.
- Only surface_id=PRIMARY_SEEN and truth_partition=PRIMARY_TERMINAL rows are
  sent through the five heads or joined to labels.
- surface_id=HELDOUT_TEMPLATE and truth_partition=TEMPLATE_ESCROW rows may
  exist in the shared feature cache, but this source unit never predicts on
  them and never opens their escrow file.
- Primary label rows are ordered by the filtered primary row manifest and
  joined on row_id, quartet_id, and variant_id.
- The terminal label exact_target is the candidate position/class 0..2.
  target_candidate_identity is the semantic state identity, and
  candidate_identity_order[exact_target] must equal it.
- Identity endpoints include every primary row. Relation and observed-state
  endpoints use only rows where both frozen term IDs are below 16. Exact-target
  endpoints select by the four frozen score_strata values.
- Bootstrap strata come from the corresponding task label on variant A, even
  when endpoint selection contains only a subset of the quartet's rows.

## Frozen qualification

Endpoint order is the contract order: context identity, entity identity,
relation, observed state, then exact target in-domain, context-novel,
entity-novel, and both-novel. Balanced accuracy is reported per endpoint.
Each endpoint requires at least 200 rows per class and a whole-quartet,
class-stratified PCG64 bootstrap with 10,000 replicates, seed 2026092604,
replicate chunks of 64, a linear quantile at alpha 0.00625, and a lower-bound
floor of 0.90. The bundle passes only when all eight endpoints pass.

On a support failure, the endpoint is recorded as FAIL_SUPPORT, its bootstrap
is skipped, and no RNG draws are consumed for that endpoint. This does not
drop the endpoint from the all-eight conjunction.

## Authorization boundary

validate_scoring_authorization accepts only FAS_E4_0_STAGE_AUTH_V01 for
FRESH_SCORING, with exact predecessor roots, contract hashes, output root,
validity interval, and stage-only scope. The only enabled scope flags are
evaluation_label_opening and scoring. run_authorized_primary_scoring
validates that receipt before head inference; OneShotPrimaryLabelReader
validates it again immediately before its single binary label-file open and
refuses a second attempt. The caller must verify the sealed population,
parity, feature-cache, and E3 head artifacts before entering this source unit.

The synthetic tests use temporary label/manifest/cache files and synthetic CPU
head files only. They do not read actual E4 artifacts, actual E3 observer files,
or any frozen E4 terminal labels; they do not initialize CUDA.

## Sealed one-shot CLI

`runner.py` is the only execution wrapper. By default it resolves the workspace
from its source location and expects the scoring authorization at
`audits/e4-0-fresh-scoring-authorization-v01.json`; `--authorization` may name
the exact authorization file and `--workspace-root` may name the managed
workspace. The run root comes only from the authorization's `output_root`.
`--preflight-only` verifies contract and predecessor seals, audits, every E4
stage seal, the complete row manifest and feature cache, all frozen E3 head
member hashes, and the exact stage authorization without inference or label
access.

The full command requires a valid `FRESH_SCORING` authorization. It validates
all sealed identities before the first label-file open, predicts only rows
whose manifest custody is `PRIMARY_TERMINAL`, then opens the primary terminal
label file exactly once. The escrow member path is obtained as seal metadata
only; the scorer does not call `open`, hash, or parse that file. A second
attempt against the same `score/` directory is refused. New outputs are
installed atomically without replacement. A post-start exception preserves
any completed artifacts and writes `score/score-stop-v01.json`; it does not
overwrite an existing stop receipt.

The preflight consumes the stage artifact IDs emitted by `e4_runner_modes_v01.py`:

| Stage seal | Required member IDs read by Track C |
| --- | --- |
| `parity-panel/stage-seal-v01.json` | `panel_inputs`, `panel_row_manifest`, `selection_receipt` |
| `parity/stage-seal-v01.json` | `gpu_lease_receipt`, `parity_receipt`, `online_feature_cache` |
| `features/stage-seal-v01.json` | `gpu_lease_receipt`, `feature_extraction_receipt`, `feature_cache`, `population_row_manifest` |

The population seal retains its independently frozen IDs, including
`E4_POPULATION_ROW_MANIFEST_V01`. Track C requires the feature-stage
`population_row_manifest` entry to match that population member byte-for-byte;
it does not alias or rename either sealed artifact.

## Scoring output schema

The scorer seals the following files in `score/stage-seal-v01.json` with the
generic `FAS_E4_0_ARTIFACT_SEAL_V01` format. The terminal receipt is a member of
that seal; the seal does not recursively bind itself.

| Artifact ID | Relative path | Contents |
| --- | --- | --- |
| `E4_SCORING_PREDICTIONS_V01` | `score/predictions-v01.jsonl` | One primary row per line; no truth labels. |
| `E4_SCORING_SCORED_ROWS_V01` | `score/scored-rows-v01.jsonl` | Primary row identity, joined terminal labels, and five frozen head predictions for independent replay. |
| `E4_SCORING_METRICS_V01` | `score/metrics-v01.json` | Eight endpoint metrics, support, bootstrap lower bounds, and bundle disposition. |
| `E4_SCORING_BOOTSTRAP_V01` | `score/bootstrap-v01.npz` | Ordered per-endpoint bootstrap balanced-accuracy arrays. |
| `E4_SCORING_LABEL_OPEN_RECEIPT_V01` | `score/label-open-receipt-v01.json` | Primary label SHA-256/bytes/row count and one-open custody receipt. |
| `E4_SCORING_TERMINAL_RECEIPT_V01` | `score/terminal-receipt-v01.json` | Authorization, predecessor roots, terminal disposition, output paths, and forbidden-action counters. |

Prediction JSONL has exactly these top-level fields:

```json
{
  "row_index": 0,
  "row_id": "...",
  "quartet_id": "...",
  "variant_id": "A",
  "surface_id": "PRIMARY_SEEN",
  "truth_partition": "PRIMARY_TERMINAL",
  "head_predictions": {
    "context_identity": 0,
    "entity_identity": 0,
    "relation": 0,
    "observed_state": 0,
    "exact_target": 0
  }
}
```

`scored-rows-v01.jsonl` uses those row-identity fields, then `labels` (the exact
primary terminal record) and `head_predictions`. No escrow row is present in
either JSONL file.

The metrics JSON schema is `fas-e4-0-fresh-qualification-v01`. It contains
`endpoint_order`, the frozen bootstrap/support/floor settings, and `endpoints`
in that same order. Each endpoint records rows, accuracy, balanced accuracy,
class IDs/support, per-class recall, confusion matrix, `SCORED` or
`FAIL_SUPPORT`, bootstrap lower bound and alpha, and its individual gate result.
`passed_endpoints`, `failed_endpoints`, `bundle_qualified`, and
`terminal_disposition` provide the all-eight conjunction. Bootstrap arrays are
removed from metrics and stored in NPZ.

The NPZ key order is fixed to `ENDPOINT_ORDER`:

```text
endpoint_00__bootstrap_balanced_accuracy  context_identity
endpoint_01__bootstrap_balanced_accuracy  entity_identity
endpoint_02__bootstrap_balanced_accuracy  relation
endpoint_03__bootstrap_balanced_accuracy  observed_state
endpoint_04__bootstrap_balanced_accuracy  exact_target_in_domain
endpoint_05__bootstrap_balanced_accuracy  exact_target_context_novel
endpoint_06__bootstrap_balanced_accuracy  exact_target_entity_novel
endpoint_07__bootstrap_balanced_accuracy  exact_target_both_novel
```

Each scored endpoint array contains 10,000 float64 values. A `FAIL_SUPPORT`
endpoint has an empty float64 array; the implementation skips its bootstrap and
consumes no RNG draws. The terminal receipt schema is
`FAS_E4_0_FRESH_SCORING_TERMINAL_V01`, with `authorization_id`, authorization
and contract hashes, `exact_predecessor_roots`, primary rows scored, zero
held-out rows inferred, label open count one, false refit/tuning/alternate-view
flags, endpoint pass/fail lists, output paths, and the exact terminal
disposition (`PASS_SIMULTANEOUS_FRESH_BUNDLE_QUALIFICATION` or
`FAIL_FRESH_QUALIFICATION`).
