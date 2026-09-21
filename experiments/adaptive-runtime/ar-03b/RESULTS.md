# AR-03B results

Status: completed diagnostic-only frontier. No proxy controlled training, and no end-to-end optimizer comparison was run.

## Integrity

- Protocol/source freeze: `0bbf47a2` (parent R2 baseline `564613ffe1e0f80ea09021093c574f6e0ae51a83`).
- Replayed 18 R2 evaluation streams across the nine dataset×initialization cells; captured 162 states.
- All 54 R2 checkpoint checks passed: parameter fingerprint, candidate count, exact candidate utilities, and full-gradient partition IDs. Model-state and three dataset hashes match the frozen receipt.
- All candidate responses, training losses, and proxy features were finite; hash and proxy partitions were 12×8 balanced.
- Output validation passed: JSON parsed; every CSV row matched its header width; 54 integrity rows, 162 snapshot rows, and 288 cost projections were present. Every frontier-summary group retained all nine cells at its exact state/anchor.
- Runtime: 178.63 seconds. Local optimized-build timings are diagnostics, not portable performance claims.

## Verification quality

At V48, every non-hash partition—including the full-gradient reference—had lower observed panel RMSE than the equal-weight hash-placebo mean in all 54 stream×checkpoint observations (18 streams at each of steps 600, 2,400, and 4,200). The equal-cell analytic RMSE comparison was favorable in all 27 cell×checkpoint points. These are nested observations; the replication unit remains the nine crossed cells.

| Checkpoint | Hash-placebo RMSE | Full-gradient RMSE | Output-layer RMSE | Output gain vs hash | Full-gradient gain retained |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 600 | 3.4985e-4 | 2.4543e-4 | 2.4780e-4 | 29.2% | 97.7% |
| 2,400 | 6.5003e-4 | 5.6616e-4 | 5.6446e-4 | 13.2% | 102.0% |
| 4,200 | 7.3234e-4 | 6.6774e-4 | 6.6232e-4 | 9.6% | 108.4% |

The “retained” ratio is `(hash RMSE − output RMSE)/(hash RMSE − full-gradient RMSE)`; values above 100% mean the output-layer partition had lower aggregate RMSE than the full-gradient partition at that checkpoint, not that it universally dominates. Output-layer sign error, cross-block regret, selected-program regret, and false authorization are in `summary-v48.csv`; all are V48-only decision telemetry.

At age 100, output-layer partition RMSE was within 0.3% of a freshly rebuilt output partition at both anchors. Across the tested proxies and six age readouts, equal-cell aggregate stale-vs-fresh RMSE shifts were small (absolute maximum below 1%). This supports reuse as a diagnostic possibility on these frozen paths; it does not establish an adaptive refresh policy.

## Cost/quality frontier

The partition build, not feature acquisition, dominates proxy refresh cost. At anchor 600, mean measured output-layer acquisition was about 10.6 μs for all 96 examples, followed by 1.97 ms for balanced partitioning. At anchor 2,400 those components were about 10.5 μs and 2.69 ms. Full-gradient refresh totaled 4.37 ms and 5.22 ms, respectively. The eight hash placebos together took about 14 μs to construct. V48 candidate verification took about 0.517 ms at anchor 600 and 0.530 ms at anchor 2,400.

The cost projection amortizes measured feature+partition refresh and adds measured verifier time; it excludes unmeasured runtime overhead and is not a measured training runtime. At reuse age 100:

- At the 600 anchor/readout 700, output-layer V36 had predicted RMSE 3.5503e-4 versus hash V48 at 3.7473e-4, with projected component cost 407.7 μs versus 517.0 μs (21.1% lower; 25% fewer candidate-example evaluations).
- At the 2,400 anchor/readout 2,500, output-layer needed V48 to beat hash V48 on predicted RMSE: 5.8230e-4 versus 6.6394e-4. Projected component cost was 556.5 μs versus 529.7 μs (5.1% higher).
- Averaged over both age-100 readouts at V48, output-layer RMSE was 4.2974e-4 versus hash at 5.2025e-4, while projected cost was 546.6 μs versus 523.3 μs. Full-gradient V48 was slightly more accurate (4.2632e-4) but costlier (571.1 μs).

Thus the compute-adjusted case is promising but state-dependent: the early anchor offers a lower-cost evidence-size trade, while the later anchor buys better RMSE at a modest component-cost premium. RMSE values below V48 are analytic finite-population estimates; decision-error metrics were not sampled below V48.

## Interpretation and boundary

H47’s gradient-response geometry remains useful with compressed representations on these same R2 cells. The output-layer 27D proxy is the clearest efficiency candidate: it retains essentially all aggregate V48 RMSE benefit at much lower acquisition and partition cost than the full 171D feature. However, balanced K-means still costs milliseconds, so refresh amortization is necessary for the component-cost frontier to look attractive.

This is not evidence that output-layer strata improve training, generalize to a new task, or should control a runtime. No learned feature, controller use, or AR-03C training comparison was performed. The next gate remains an explicitly authorized end-to-end test only after review of this frontier.

## Artifact note

The original `cost-projection.csv` is preserved as emitted by the frozen run. Its observed-V48 columns are blank because the initial writer joined the analytic frontier table rather than the separate V48 summary table. `cost-projection-v48-joined.csv` is a post-run join of those already-validated tables; it adds the corresponding observed V48 RMSE and decision metrics without recomputing any candidate utility or replaying training. A follow-up source fix makes future runs write this join directly. All raw measurement tables remain unchanged.
