# FAS-S01 S01-2B tokenizer boundary audit, v02

This read-only audit uses only the sealed S01-2 corpus and S01-2A tokenizer output. It preserves the S01-2A `TOKENIZER_ALIGNMENT_FAIL_CLOSED` disposition and does not modify either parent.

Attempt v01 remains as an unsealed implementation draft. Its preflight root was `2d540a0474d3da63e6b70a434c205a1b85d8ae55a7f41b6087c199956bbff217`. Review found a spill-category spelling mismatch and a missing quartet-level reduction over the four variant results. This v02 rerun keeps the frozen audit criteria and adds reducer self-tests; attempt v01 outputs are not inputs.

The audit records all 638,976 required span occurrences, exact crossing-token offsets and spill text, spill widths and categories, coverage diagnostics, term/template identities, and minimal-cover diagnostic counts. Those diagnostics do not adopt an alignment rule or punctuation allowlist.

No tokenizer is loaded or called. No LFM weights, features, probes, or geometry are used. Feature extraction remains ineligible, and S01-3 remains unauthorized.
