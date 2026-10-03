# REQUAL1-RIS1-DOMAIN v3: fresh pair-opportunity derivation

This engineering-only identity derives a fresh pair-opportunity domain from
the current REQUAL1 singleton materialization. It does not replay pairs and
does not import historical 704 or 3,753 counts. Domain v2 is preserved as a
diagnostic predecessor because its selector declaration and parent-lock gate
were not fully enforced.

The v3 selector is defined entirely by its sealed CONTRACT.json: explicit
geometry and collateral sort keys, deterministic `(group,to)` terminal ties,
and round-robin fill over `(group,axis_sign,opposition_sign)` buckets. The
reference state is a current exact replay of the matching PAR8
`best_search` mapping; its historical score is never imported.

The pair domain contains every canonically ordered pair of selected singleton
records from different raw groups within the same current context. Pair
records are domain records only. No pair state, pair readout, pair geometry,
behavioral probe, scientific seed, or promotion is permitted here.

The run fails closed on status, parent identity, exact expected-parent hashes,
singleton hash/score/geometry drift, missing current PAR8 reference, illegal
prefix, duplicate candidate, selector cardinality ambiguity, or missing
current source.
