# Q_terminal semantic calibration v04

This follow-up keeps the raw action-semantic composition in v03 unchanged. It fits a nondecreasing isotonic map from v03's summed per-clause log satisfaction score to validity probability. Only the 520 Q-v02 training rows and their validator labels enter pool-adjacent-violators fitting; validation and test labels are used for evaluation only.

## Run

```powershell
python experiments/fas-r1-semantic-particle-reachability-v00/stage1-v01/qterminal/semantic-composition-v04/calibrate_semantic.py
```

The default output is `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-semantic-v04`. Existing outputs are never overwritten. The script checks the v03 source, manifest, receipt, report, candidate score artifact, Q dataset, support roster, selected-candidate labels, and fitted-Q provenance before it fits.

## Runtime package

`identity-head-f32le.bin` and `identity-head-export.json` are byte-identical copies of the v03 identity-head export. `isotonic-coefficients.f64f32le.bin` contains the sorted inclusive upper score bounds as little-endian float64, followed by calibrated validity probabilities as little-endian float32. `isotonic-export.json` provides offsets, lengths, hashes, and the binary-search rule: choose the first upper bound greater than or equal to the semantic log score, and clamp values above the final bound to the final probability.

## Reading the result

The report provides raw, calibrated, and Q-v02 metrics over the same train/validation/test candidates, then breaks test results into the two identity-sensor training-overlap families (11 rows) and two families unseen to identity training (13 rows). The raw v03 diagnostic already ranks all 24 selected test candidates correctly and ties Q-v02 at 100% top-1 valid rate on four candidate pools; calibration is evaluated as a probability-quality repair, not a source of new ranking reachability.
