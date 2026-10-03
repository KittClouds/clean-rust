# Q10-WC result

Status: `Q10_WC_VALID__DESCRIPTIVE_ASSOCIATIONS_REPORTED`

The frozen Q10-SM constructor was replayed on 5,120 fresh engineering states. A safety-margined nonidentity endpoint was available in 5,043 states (`98.49609375%`); 77 states were safety-margin dominated. The independent standard-library reviewer recomputed coverage, geometry integrity, correlations, and descriptive models from the raw receipts.

The accepted wedge remained narrow: median rotation `0.004136999934092628` radians (`0.2370` degrees), interquartile range `0.002018175036516081` to `0.007409345063249365` radians, and maximum `0.0520156293340325` radians (`2.9802` degrees).

The clearest descriptive correlate was true-endpoint safety slack. Its pairwise Spearman association with rotation angle was approximately `+0.59`, and every leave-one-seed-out estimate remained positive (`0.584` to `0.603`). Reversal time was weaker and negative at approximately `-0.18`. Active boundary fraction was near zero (`+0.05`); support size, nullity, and null-energy fraction were weakly negative (approximately `-0.08`, `-0.08`, and `-0.09`). The prespecified core descriptive model was full rank with `R^2 = 0.3980` and condition number `32.93`.

These are geometry-only associations. They do not establish that changing slack causes a wider wedge, do not select a future direction threshold, and do not authorize behavior or DH-08B.
