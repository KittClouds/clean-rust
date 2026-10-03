# S05 S02 Diagonal Binding Correction v07

The v06 replay reached the pre-update FAS-00 diagonal comparison after
calculating the fixed logits, then stopped because the event-population
records did not carry the two already-sealed S02 predictions under the
explicit `s02_mean_prediction` and `s02_final_prediction` keys. No S05 metric,
paired table, or result file was emitted.

This correction copies those two immutable prediction labels into the
population record from the sealed S02 mean and final prediction rows. A unit
test verifies that the view identities remain distinct. The replay and
diagonal gate remain unchanged. This v07 attempt uses its own output directory.

No model contact, feature extraction, probe fitting, or adaptive mechanism is
authorized or performed by this correction.
