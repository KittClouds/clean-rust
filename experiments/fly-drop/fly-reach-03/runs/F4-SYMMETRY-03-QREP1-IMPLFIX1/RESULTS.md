# F4-SYMMETRY-03 Results

Qualification-only fresh crossed-regime replication. RUN4 and SYMMETRY-02 were not re-sliced or pooled.

- Fresh task blocks: 304000, 304001, 304002, 304003, 304004, 304005, 304006, 304007.
- Common scored rows: 16342.
- Pooled IPW-balanced error, C: 0.344040317; D: 0.0767680448; D-C: -0.267272272.
- Pooled signed margin, C: 2.25285685; D: 5.18197682.
- Pooled Psi, C: 0.730753184; D: 0.88348057; D-C: +0.152727387.
- Cross-block 0011 rule: 1/8 positive; NOT_SUPPORTED.

## Pattern-conditioned D-C effects

| Pattern | Rows | Error C | Error D | Psi C | Psi D | Delta Psi D-C | Additive pooled Delta Psi share |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0011 | 914 | 0.5 | 0.2366369710467706 | -0.11887002187867524 | -0.11394858756012294 | 0.004921434318552298 | 0.00012771030510350917 |
| 0101 | 0 | None | None | None | None | None | 0.0 |
| 0001 | 3987 | 0.33883563810070466 | 0.0 | 0.9481697553821822 | 1.0 | 0.05183024461781782 | 0.005195632076021738 |
| 0100 | 1026 | 0.5157855268591413 | 0.004015060100279838 | -0.9330009987147423 | -0.17237599138882098 | 0.7606250073259213 | 0.03363005538455718 |

## Leverage concentration

Pooled and pattern summaries report effective sample size and top 1%, 5%, and 20% leverage shares in `ANALYSIS.json` and `FINAL-OUTCOMES.csv`. Large Psi values describe the declared first-order consequence weighting; they do not imply broad row-wise accuracy or trajectory improvement.

## Block by pattern

See `BLOCK-PATTERN-SUMMARY.csv` for all 8×16 cells, including empty cells.

## Interpretation boundary

Qualification replication only. A positive result supports repeatability within these structurally selected blocks; it is not a population-level or biological claim. Psi is local first-order alignment and does not guarantee trajectory improvement.
Measured REACH-03 remains closed; no controller or PHENO work was opened.
