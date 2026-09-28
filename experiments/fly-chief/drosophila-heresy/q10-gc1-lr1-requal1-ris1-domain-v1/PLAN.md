# REQUAL1-RIS1-DOMAIN: fresh pair-opportunity derivation

This engineering-only identity derives a fresh pair opportunity domain from
the current REQUAL1 singleton materialization. It does not replay pairs and
does not import the historical 704 or 3,753 counts.

The selector is a current-lineage port of the documented legacy shortlist
shape: up to 16 geometry-ranked singleton candidates, up to 8 collateral and
score-ranked candidates, then deterministic round-robin bucket fill to at most
32 candidates per context. All selector fields are recomputed from current
singleton receipts and current exact replay. A current replay of the matching
PAR8 best-search mapping supplies the reference state for signed axis and
linear-drive direction features; its historical score is never imported.

The pair domain contains every ordered-canonical pair of selected singleton
records from different raw groups within the same context. Pair records are
domain records only. No pair state, pair readout, pair geometry, behavioral
probe, scientific seed, or promotion is permitted here.

The run fails closed on any singleton hash/score/geometry drift, missing
current PAR8 reference, illegal prefix, duplicate candidate, selector
cardinality ambiguity, or parent-hash mismatch.
