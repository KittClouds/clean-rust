# REQUAL1-SREPLACE-DOMAIN: fresh S-replacement shortlist and pair domain

This engineering-only identity derives a deterministic current-lineage
shortlist and pair domain from the complete
`REQUAL1-SREPLACE-SINGLES` receipts. It starts from the fresh invalid `S`
state semantics, but performs no replay and imports no historical LR1
selector, count, or pair result.

The selector excludes exact no-op replacements, then uses fixed geometry,
collateral, and signed-debt-bucket lanes. Each context receives at most 32
unique singleton candidates. The pair domain contains every unordered pair
of selected candidates from distinct groups in that context. Pair replay is
forbidden in this identity; the resulting domain is only a sealed input for a
later fresh pair-replay identity.

Whole-endpoint science remains closed. Historical SALL1/LR1 artifacts remain
archaeological and are not inputs.
