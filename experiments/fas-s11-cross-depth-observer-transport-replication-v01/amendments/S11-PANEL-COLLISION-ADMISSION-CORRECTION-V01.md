# FAS-S11 Panel Collision Admission Correction v01

Status: construction-only correction, frozen before tokenizer or model contact.

## Parent and reason

This correction is bound to the sealed S11 protocol root `9f11fb59d0f01ed12ee9c9f1753ae990ce5bcb20cf4f799d35a11a39079a4598` and the unchanged v01 candidate universe, seed, renderings, class quotas, and support requirements.

The first deterministic panel construction followed the sealed hash ranking and met the three class quotas, but failed its independent uniqueness gate: 5,318 ranked quartets contained 21,272 event rows with 189 repeated rows across 170 repeated rendered-input hashes. The attempt is preserved at `panel-construction-v01` as `PANEL_CONSTRUCTION_FAIL_CLOSED`.

This was detected before tokenizer loading, model loading, feature extraction, observer access, or outcome analysis. No performance result or prior label entered this correction.

## Corrected admission rule

Keep the exact original candidate universe, generated inputs, identity scheme, seed, canonical candidate key, and SHA-256 selection ranking. For each exact-target class in ascending class ID `0, 1, 2`, traverse ancestry-fresh candidates in ascending `(selection_sha256, ordinal)` order. Admit a quartet only when all four rendered-input hashes are distinct within that quartet and absent from every previously admitted quartet. Record a skipped candidate as `INTRA_PANEL_DUPLICATE_REJECTED`; do not change its rank or replace its seed. Continue through the same complete class candidate list until that class reaches its original fixed quota.

The uniqueness set spans the complete selected panel. A quartet is indivisible: any input collision rejects all four events from that candidate. Candidates not reached before their class quota is filled remain `NOT_SELECTED`. Ancestry freshness rejection continues to take precedence. If any class quota or frozen family/template support requirement fails, fail closed without reseeding or relaxing the gates.

## Unchanged science and authority boundary

This amendment changes only deterministic construction admission needed to satisfy the already frozen zero-duplicate input gate. It does not change the scientific estimands, bootstrap plan, observer bank, feature protocol, worlds, templates, terms, labels, classes, quotas, or task. S11 model contact, tokenizer contact, feature extraction, and observer replay remain unauthorized by this correction. This amendment authorizes panel construction and validation only.

## Construction-only diagnostic

Applied to the v01 hash-ranked candidate ledger before any model contact, the rule yields the same quotas `1733 / 1815 / 1770`, 5,318 quartets, 21,272 unique input rows, all eight families, all eight observation templates, all eight query templates, and all 64 observation/query template cells. The new v02 panel must independently reproduce these values from the unchanged candidate universe before it can be sealed.
