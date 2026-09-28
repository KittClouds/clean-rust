# Q10-GC1-D1-R1: Contextual Removal Replay

D1-R1 is new counterfactual evidence, separate from D1. It answers group
attribution without pretending support overlap is causality.

For every selected active group in each of the 28 labeled saved valid/search
states, replace only that group's choice with ZERO, retaining all other
choices. Materialize from baseline with the qualified RQ1 runtime and replay
the full endpoint with exact sequential-f32 and full PF5 geometry.
Deduplicate identical weight states but retain every intervention label.
Report the exact preflight count; upper bound is twice 801 groups before
active-group filtering and dedup.

Record `g(W)-g(W_without_group)` row-wise deltas, score changes, reopened
repairs, collateral repaired/created, and geometry changes. An ablation need
not pass final geometry to be diagnostic, but cannot become a valid
constructor output unless all gates pass. Call these leave-one-group-out
contextual effects. Do not sum them as an allocation; sequential-f32
interactions can make that sum wrong. No greedy deletion sequence.

Gate: complete map semantics, exact replay, full legality, unchanged parents.
Uses RQ1 predicates and atomic receipts. No beam search, fresh seeds, or
behavior.
