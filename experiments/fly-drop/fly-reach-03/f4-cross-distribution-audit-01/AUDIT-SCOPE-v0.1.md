# F4 Cross-Distribution Failure Audit v0.1

**Status:** analysis-only archaeology; no refits or representation changes.

## Question and boundary

Compare the sealed F4-SYMMETRY-03 qualification distribution with the sealed F4-CALIBRATION-02-QPROMO2 ordinary-task distribution to describe which measured distribution properties differ alongside D's calibration result. This audit does not estimate a causal effect of task selection, change either run, reopen calibration, or authorize measured REACH-03.

The SYMMETRY-03 observations come from `F4-SYMMETRY-03-QREP1-IMPLFIX1` (blocks 304000–304007), whose task blocks were chosen by the declared structure-only screen. QPROMO2 uses fresh ordinary blocks 305012–305023 with no structural pattern selection. Both use four cues, 8,192 trials per block, twelve delay positions, nine substrates, two sides, and the same task schedule generator family.

## Frozen inputs

Only the following sealed artifacts may be read:

- SYMMETRY-03 native collection: `RAW-PREDICTORS.bin` SHA-256 `41bb93ca9a20036aaff513f220b7511442b83eb22d12cac9709adc1fc839e525`; `RAW-SCORING-TRUTH.bin` SHA-256 `4f0609d5f80f43c7f3d5eefefb496c0329e21c50430f08b7b74b826bd307a218`.
- QPROMO2 native collection: `RAW-PREDICTORS.bin` SHA-256 `344e3e129665df2a0ccac2b6c0f12b9b59a76a5fe39e38627df151738377c390`; `RAW-SCORING-TRUTH.bin` SHA-256 `cab0340a2846c2582cbb61b040cef0af0b28476a37a8680239dbaf8685f836b7`.
- Their task-bank training payloads and task/collection receipts, checked against the hashes recorded in the sealed manifests.
- Their already sealed analysis and terminal receipts for previously reported calibration outcomes.

The analyzer must verify all of those hashes and run identities before calculating summaries. It must not write into either source run directory.

## Fixed summaries

1. **Task-only structure:** task-selection status; block count; cue, trial, and delay counts; positive/negative cue-label counts and label-assignment diversity; pooled first-cue frequency dispersion; pooled delay-token frequency dispersion. These are computed from task-bank metadata only.
2. **Scored U* support:** total scored rows; rows by frozen block; number of nonempty substrate-by-side streams per block; row-count minimum, median, and maximum; class-complete block count and IDs.
3. **Class balance:** pooled observed positive/negative counts and inverse-inclusion-probability-weighted class shares, plus the fixed per-block class counts. Empty and one-class block scores remain undefined.
4. **Target margins:** absolute reference-target magnitude on scored U* rows, with unweighted and inverse-inclusion-probability-weighted quantiles at 1%, 10%, 50%, 90%, and 99%, plus weighted fractions at or below the already used thresholds 1e-12, 1e-10, and 1e-8. No new margin cutoffs or row exclusions.
5. **Leverage concentration:** using the frozen definition `q * abs(native_proposed_update) * abs(reference_target)`, report total leverage, effective sample size and its row fraction, and top 1%, 5%, and 20% leverage shares. Also report the minimum, median, and maximum blockwise ESS and top-5% share; do not subdivide by incidence pattern or model correctness.
6. **Outcome anchor:** copy the already reported pooled D error and Omega-hat for each run from its sealed analysis receipt. Do not load or score prediction streams anew.

## Interpretation limits and stop

This is descriptive archaeology across two task distributions and two qualification identities. Differences cannot be attributed solely to structural screening because block seeds and task schedules also differ. No hypothesis tests, new fits, prediction replays, pattern-conditioned analyses, or feature work are in scope. After producing the hash-checked audit report and receipt, stop. Any new encoder belongs to a separately specified qualification branch.
