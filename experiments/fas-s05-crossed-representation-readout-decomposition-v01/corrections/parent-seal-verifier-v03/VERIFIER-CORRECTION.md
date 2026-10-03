# S05 Parent Seal Verifier Correction v03

This version preserves the original S05 v01 protocol seal and the separately
sealed v02 canonicalization correction. Neither failed preflight wrote event
population or analysis artifacts.

The v02 verifier correctly implemented the declared S02 UTF-8 path ordering
and the S01 path/byte-length/hash tree algorithm. It resolved S01's relative
entry paths from the seal's `seals` subdirectory, though. The S01-3 result
manifest paths are rooted at the S01-3 run directory. An independent read-only
check verified all 128 entry hashes, byte lengths, and the declared root from
that run directory.

This v03 correction changes only that S01 parent root directory. It preserves
the S05 corpus, analysis contract, metrics, arithmetic, readout states, and
scientific scope. It writes to a distinct S05 v03 run directory. No model
contact, feature extraction, probe fitting, or adaptive mechanism is
authorized or performed by the correction.
