# Q_terminal semantic logistic calibration v06

This version keeps v03 raw composition, v04 isotonic calibration, and the v05 fit contract unchanged. It fits one regularized monotone logistic map from the raw semantic log-product score to confidence. The fit uses only the 520 Q-v02 training rows and their validator labels; validation and test labels are evaluation-only. The fixed Rust reference vector uses an opaque identifier and omits sample, task, and feature IDs so identifiers cannot disclose candidate validity.

## Run

```powershell
python experiments/fas-r1-semantic-particle-reachability-v00/stage1-v01/qterminal/semantic-composition-v06/calibrate_logistic.py
```

The default output is `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-semantic-v06`. Existing outputs are never overwritten. The source manifest pins v03, v04, Q-v02 data/checkpoint, public tasks, extraction, and identity model hashes.

## Runtime package

The frozen identity linear head is included unchanged. `logistic-calibration-f64le.bin` contains five float64 little-endian coefficients in order: negative-infinity floor, train score center, train score scale, nonnegative standardized slope, intercept. Apply `sigmoid(intercept + slope * ((score_or_floor - center) / scale))`. Raw score remains available for selection; logistic probability is a confidence output.

`rust-composition-reference-v01.json` contains one full candidate's public H vectors, expected identity logits/probabilities, incidence-supported kind mask, candidate assignment, per-clause expected satisfaction, and final log score. It contains no validator label, private clause kind, or label-revealing source identifiers. The run checks it against the frozen Python v03 outputs before writing its receipt.

## Test strata

The Q-v02 test comprises two families overlapping identity-sensor training (11 candidate rows) and two unseen to identity training (13 rows). The report keeps these groups separate. Isotonic v04 probability alone can collapse raw score ties; v05 reports it alongside raw ranking, ridge-logistic confidence, Q-v02, and the private-kind oracle diagnostic.
