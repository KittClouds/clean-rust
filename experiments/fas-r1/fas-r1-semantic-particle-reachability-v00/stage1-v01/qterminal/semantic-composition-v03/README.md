# Q_terminal semantic composition v03

This is a read-only scoring alternative over the existing Q-v02 prepared rows. It does not fit a model, calibrate, contact the LFM, or modify the Q-v02 artifacts.

## Run

From the active managed worktree:

```powershell
python experiments/fas-r1-semantic-particle-reachability-v00/stage1-v01/qterminal/semantic-composition-v03/score_semantic.py --device cpu
```

The default result is `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-semantic-v03`. The script refuses to overwrite an existing result. It validates the pinned source/data/model hashes, checks JSONL-to-array row identity and public/private clause-incidence joins, and recomputes Q-v02 with the stored validation temperature before scoring.

## Scoring

The frozen identity linear head predicts six clause-kind probabilities from each constraint vector. Public entity/role incidence determines which kinds have all required arguments; unsupported kinds are masked and the remaining posterior is renormalized. The per-clause expected satisfaction is composed with the complete candidate assignment. The terminal score is the sum of per-clause log probabilities, with exact zero preserved as negative infinity. This is a factorized approximation across clauses.

The private-kind oracle is diagnostic only. It uses the same public incidence/assignment rule with offline private clause kinds and must match every typed-validator candidate label exactly.

## Rust head export

`identity-head-f32le.bin` contains little-endian float32 arrays in the order and offsets declared by `identity-head-export.json`: mean, standard deviation, standardized weights, standardized bias. The exported linear transform consumes raw float32 constraint vectors; apply softmax using the listed class order. A fixed raw feature row is compared against PyTorch before the run completes; maximum logit and probability errors are recorded in the metadata.

## Evaluation notes

The v02 Q test has four families, two overlapping identity-sensor training and two unseen to that training. Candidate row counts are 11 and 13 across those groups because family candidate counts are unequal; the scorer reports both groups separately and does not call aggregate test unseen generalization. The report also compares the semantic score with the frozen Q-v02 selector on identical rows and reports top-1 valid rate within `(feature_id, source_kind)` pools.
