# FAS-S01 S01-2B tokenizer boundary audit

This is a read-only audit of the sealed S01-2 corpus and the sealed S01-2A tokenizer outputs. The S01-2A disposition remains `TOKENIZER_ALIGNMENT_FAIL_CLOSED`; this audit does not change or supersede it.

The audit reconstructs each declared context, entity, and relation span from the serialized corpus and token offsets. It records every crossing token, its token ID and exact offset, the exact characters and widths spilling to the left and right, and metadata identifying the term, template, and string position. It also reports whether the minimal intersecting-token cover has exact once-only character coverage and whether its spill is only whitespace and/or punctuation.

Minimal-cover outcomes are diagnostic only. This phase does not adopt a span-alignment rule, define an accepted punctuation set, modify corpus text or spans, call a tokenizer, load LFM weights, extract features, or authorize feature extraction or S01-3.

The sealed result includes a new read-only audit tree. Its preflight seal binds the audit contract and scripts before scanning. The result disposition leaves feature extraction ineligible and model contact unauthorized.
