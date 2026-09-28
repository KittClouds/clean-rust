# FAS-S01-2A tokenizer alignment qualification

This is a tokenizer-only continuation of the sealed S01-2 construction. Its
input is the immutable S01-2 corpus and the already sealed seven-view feature
contract. The run loads the tokenizer at the exact pinned revision and records
token IDs, offsets, special-token masks, sequence lengths, required span maps,
and a fixed repeat check. It does not load model weights or create features.

The execution contract is under `contracts/`. It binds the corpus SHA, S01-2
protocol bundle root, S01-2 result-tree root, tokenizer revision, alignment
rule, repeat sample, output schema, and support thresholds. `source/` contains
the runner and preflight sealer. Seal the preflight package before running the
tokenizer. The runner writes only to a fresh output root and fails closed on
any identity, alignment, support, or deterministic-repeat mismatch.

An alignment-ready disposition means tokenizer spans are qualified for the
frozen seven-view extraction contract. It does not authorize LFM loading,
feature extraction, probes, geometry analysis, or S01-3.
