# S05 Population Slice Normalization Correction v05

The v01-v04 S05 preflight attempts produced no population or analysis outputs.
The sealed source prediction rows encode slice names as
`test_context_term_3` and `test_entity_term_7`, while the S05 contract's
population ledger uses `CONTEXT_TERM_3` and `ENTITY_TERM_7`. The previous code
validated the mapping but retained the source spelling, so its subsequent
contract-count check saw empty named slices.

This v05 correction normalizes the names through the already-frozen explicit
mapping after validating each row's source membership against Phase 1. It
does not change the selected event set, labels, feature rows, metrics, or
readout replay. It also strengthens the analysis receipt check to bind the
already-sealed authorization packet. The run uses its own v05 output directory.

No model contact, feature extraction, probe fitting, or adaptive mechanism is
authorized or performed by this correction.
