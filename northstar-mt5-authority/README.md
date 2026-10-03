# Northstar MT5 Research Authority

This repository preserves the MT5-side research controls, schemas, campaign
definitions, test fixtures, receipts, reports, and source artifacts that feed
Northstar's sealed market-object work.

The large observation corpus is intentionally not stored in GitHub. Its 590
payload files remain local on `D:` and are bound by:

- `local-corpus-manifest/mt5_local_corpus_manifest.tsv`
- `local-corpus-manifest/mt5_local_corpus_receipt.json`

The manifest records each local payload's original relative path, byte length,
SHA-256 digest, storage class, and availability. The receipt is evidence of the
local corpus boundary; it is not a substitute for the payload bytes.

See `BRANCH_POINT_OSV1.md` for the frozen handoff into the post-OSV1 research
branches.
