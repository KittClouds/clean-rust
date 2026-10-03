# Q10-GC1-PAR8-AUDIT1: Independent Receipt Reconstruction

AUDIT1 is a receipt-only engineering audit of the completed PAR8 global
coalition assembly. It performs no new beam search, no candidate generation,
no behavioral probe, and no scientific promotion.

The audit independently reconstructs each PAR8 `best_valid` endpoint from the
sealed PAR8 receipt, the sealed local palette library, and the frozen learner
runtime. It verifies canonical group choices, complete ZERO filling, legal
baseline-relative committed f32 bytes, exact sequential-f32 readout, whole
endpoint score, full PF5 geometry, final geometry gates, and the stored state
hashes. The lower-mismatch `best_search` state is retained as a rejected
diagnostic record when it fails final geometry; it is never treated as a
constructor output.

The audit writes only inside this directory. PAR8 and all other parent
artifacts remain unchanged. A clean result is an integrity qualification for
the PAR8 receipt, not evidence for the behavioral adaptive-state hypothesis.
