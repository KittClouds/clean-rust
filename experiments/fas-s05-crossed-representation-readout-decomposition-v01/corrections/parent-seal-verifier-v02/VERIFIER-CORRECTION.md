# S05 Parent Seal Verifier Correction v02

The original S05 v01 protocol and source bundle remain immutable and sealed at
`seals/protocol-seal-v01.json`. Its first preflight stopped before materializing
population or analysis outputs.

The failed verification path assumed one path/hash canonicalization for every
parent. The sealed S02 construction seal declares UTF-8 path-byte sorting of
`path hash` lines. The sealed S01-3 result seal declares ordinal path sorting
and hashes `path`, byte length, and file hash separated by tabs. These parent
artifacts themselves verified; only S05's generic root reconstruction was
incompatible with those declared formats.

This v02 correction adds explicit, seal-declared canonicalization handling for
those two formats. It does not change the S05 analysis contract, population,
metrics, arithmetic, replay code, parent artifacts, or scientific scope. The
v02 run writes to a separate run directory and records the original v01
protocol root as provenance.

No model contact, feature extraction, probe fitting, or adaptive mechanism is
authorized or performed by this verifier correction.
