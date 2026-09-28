# FAS-S01 S01-2C Minimal-Cover Alignment v01

This is a new alignment identity. It preserves the historical `S01-2A = TOKENIZER_ALIGNMENT_FAIL_CLOSED` disposition and does not modify S01-2, S01-2A, or S01-2B.

The sealed contract applies a minimal contiguous token cover to the existing S01-2A token IDs and offsets. It permits only zero spill or one left spill character equal to U+0020 SPACE or U+0028 LEFT PARENTHESIS, with exact once-only coverage of every semantic character. Every context, entity, and relation occurrence must pass for all four variants in a quartet.

The run reads only the sealed S01-2 corpus, S01-2A tokenizer records, S01-2B audit, and their allowlisted contracts, reports, dispositions, and seal metadata. It does not call a tokenizer, load LFM, create features, fit probes, calculate geometry, or authorize S01-3.

The frozen rule and source code are copied byte-for-byte into the D: run package and preflight-sealed before any corpus scan. Run `source/align_minimal_cover.py --run-root <run-root>` after preflight. Seal and verify the resulting tree with `source/seal_result.py --run-root <run-root>` and `--verify-only`.
