# Q10-PAIR-FRONT1: exact readout evaluation of the structural valid frontier

FRONT1 consumes the immutable valid-pair frontier sealed by EXH1. It performs
exact sequential-f32 readout only for those 9,530 structurally valid pairs.
The valid list is frozen before readout and no invalid structural pair is
replayed.

The primary success is a distinct committed endpoint whose exact sequential
readout equals the target readout and whose inherited geometry and legality
gates pass. If found, evaluation stops at the first ordered occurrence and the
candidate is retained for independent audit. If none is found, FRONT1 reports
that the complete tested disjoint order-2 structural domain contains no exact
alternative; it does not establish global infeasibility.

This is engineering-only. GC2, AG1, behavior, global assembly, and scientific
seed bundles remain closed.
