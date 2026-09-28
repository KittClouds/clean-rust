# Jev-like Source Authority Audit v0.2

Audit date: 2026-09-19. This is a metadata and schema audit only. No full
corpus was downloaded into the repository. Revisions below are pinned for the
bridge pilot and must be rechecked before any later ingestion.

## Candidate source disposition

| Source | Snapshot / revision | License metadata | Schema evidence | Disposition |
| --- | --- | --- | --- | --- |
| `sr5434/multitask-classification-dataset` | HF `795d472566a56aa94b139e3e041d2088527f30af` | not declared in current Hub metadata | `input` is JSON containing text, instruction, choices; `label` is a one-hot float list; train 1,348,090, test 192,430 | conditional adapter; quarantine primary use until license/source lineage audit |
| `tasksource/zero-shot-label-nli` | HF `ee693dba923b5d5484aa9232b7357c5e45dd39b8` | `other` | default config has premise, hypothesis, task, and 3-way class label; 1,090,333 train, 14,419 validation, 14,680 test; aggregate task field spans many upstream tasks | audit-only aggregate; no independent benchmark split |
| ChaosNLI | GitHub `easonnie/ChaosNLI` master `f358e234ea2797d9298f7b0213bf1308b6d7756b` | upstream README reports CC BY-NC 4.0; verify artifact terms | JSONL label counts and distributions, 100 annotations per item, 4,645 items; links back to SNLI/MNLI/Abductive NLI | accepted only with external snapshot receipt and upstream lineage |
| `google-research-datasets/go_emotions` raw | HF `add492243ff905527e67aeb8b80c082af02207c3` | Apache-2.0 | raw train 211,225 rows; rater ID, item ID, 28 one-hot emotion fields; one rater row per item annotation | accepted for empirical annotator distribution |
| `clinc/oos-eval` | GitHub master `828f8093932c8fe6ca7936c3d2e52903b1c523de` | repository API reports no SPDX assertion; verify license file | source repository contains in-scope intents and out-of-scope examples | conditional; accepted only after license and label-inventory receipt |
| `AmazonScience/massive` | HF `ff6bd8e4b27c3543e4f8fe2108f32bb95a6f8740` | CC-BY-4.0 | 54 locale configs; utterance, hard intent, inline `annot_utt`, slot methods, judgments; 60 intents and 55 slots | accepted for hard intent and span/type |
| `thunlp/docred` | HF `7985b4e0371e6c61a756feb41b7b27becf71c666` | MIT | train_annotated 3,053, validation 998, test 1,000, train_distant 101,873; vertexSet, labels, evidence | accepted with annotated/distant authority separation |

## Specific audit findings

`tasksource/zero-shot-label-nli` is useful for parser coverage but is not an
independent NLI source: its task field covers many upstream datasets. A row
that originates from SNLI/MNLI or another known corpus must remain linked to
that upstream identity. It cannot appear in a primary evaluation partition
alongside the same upstream item through another adapter.

GoEmotions raw is the clearest first human-disagreement bridge. The row shape
retains item ID, rater ID, and one-hot labels, so aggregation can be reproduced
from counts. The simplified config must not be treated as an independent
annotator-distribution source because it discards the rater-level structure.

MASSIVE is a strong first span/type source because its `annot_utt` field marks
slot spans in the utterance and its intent label is a separate hard target.
The adapter must preserve the original hard intent and emit slot annotations as
a separate derived view.

DocRED must keep `train_annotated` and `train_distant` separate. Distant labels
are weak supervision, and absent relation labels cannot become explicit
negative relations without a source-specific closed-world guarantee.

ChaosNLI is a strong disagreement source but not an HF Dataset Viewer source in
this audit. The bridge therefore treats its pinned GitHub/download snapshot as
an external receipt, not as a live Hub dataset.

## Audit limits

This pass did not resolve every upstream license, deduplicate full corpora, or
claim that any source is safe for a final benchmark. The generated
`source-audit.json` records this audit state and preserves conditional or
quarantined dispositions instead of promoting them by convenience.
