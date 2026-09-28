# RESID0-O2 residual audit

Read-only analysis of the complete order-2 valid frontier for `R tau4 set3`.

The frozen reference has 123 mismatches and score `[123, 162, 1.866006202952065e-05, 7.62939453125e-06]`.

Across 1438 valid order-2 states, 25 of the 123 residual rows reach their target value at least once, and 49 change relative to the reference. 74 never move in this frontier.

The frontier contains 460 distinct mismatch masks. Pairwise mask Hamming statistics: `{"maximum": 22, "mean": 5.236947627910488, "median": 5, "minimum": 0, "pairs": 1033203}`.

This is an order-2 control only. It does not classify order-3 residual authority and does not infer global reachability beyond the selected frontier.
