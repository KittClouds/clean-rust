# Jev Information-Density v0.8B: Construction Result

**Status:** `FAIL_CLOSED`; no CM100 or RM100 manifest was emitted. No model, feature extraction, or training was run. The existing v0.8 banks and StrictNovel93 remain read-only.

## Support preflight

The eligible universe contains 416,672 groups; NewTight-Eval contains 83,328. The frozen source hashes matched, and no eligible model-input signature crossed the joint-cell strata. Necessary marginal capacity checks passed for both target profiles. The smallest unused joint-cell support was 63 groups for the R100 profile and 0 for the C100 profile. These are marginal checks only; they do not prove a simultaneous input-to-root assignment exists.

| Target profile | Groups | Query views (choice / applicability / ordinal) | Unique inputs | Unique roots | Allowed root-count range |
|---|---:|---:|---:|---:|---:|
| R100 | 100,000 | 24,999 / 50,000 / 25,001 | 22,900 | 25,700 | 25,186–26,214 |
| C100 | 100,000 | 53,646 / 35,804 / 10,550 | 16,860 | 25,190 | 24,686–25,694 |

## Bounded b-matching attempts

The frozen policy allowed 16 deterministic candidate assignments per bank. Every assignment failed to reach a complete 100,000-unit input-to-root flow.

| New bank | Composition target | Selection | Flow min / median / max | Best attempt | Best-flow deficit |
|---|---|---|---:|---:|---:|
| CM100 | R100 | curated | 72,935 / 95,988 / 98,387 | #15 (index 14) | 1,613 |
| RM100 | C100 | random | 74,562 / 89,031 / 90,525 | #4 (index 3) | 9,475 |

These results establish infeasibility for the declared deterministic 16-assignment construction policy, not global infeasibility of the 416,672-group universe. Since no full assignment existed, final input/root histograms and other bank-level matching tolerances were not evaluated for a complete candidate.

## Integrity and verification

- No bank IDs or partial manifests were written; the external run directory contains only its aggregate audit report.
- Input universe, R100, C100, and NewTight-Eval SHA-256 values matched the frozen v0.8 contract.
- StrictNovel93 and all v0.8 reports were not modified. Construction read only the frozen group-record, bank/evaluation manifests, and the v0.8 contract/selector needed for identity validation. Phoenix data and model weights were neither accessed nor modified.
- `model_contact_authorized=false`, `training_banks_materialized=false`, and `phoenix_in_scope=false`.
- Tests: v0.8B `10/10` passed; v0.8 `16/16` passed; Python compilation passed.

## Sealed receipts

- Contract SHA-256: `16e8a36542ab80c9164ffe21794affd1662df8cd34dcff71858eae237c4d2c8d`.
- Construction source SHA-256: `8810694515c2c95da9f38ec53328366f6c14e3978c9837b784195c2ed926eba9`.
- Count-only preflight: `D:\codex-runs\jev-information-density-v08b\preflight-v04\factorial-feasibility.json` (SHA-256 `6106ddc55d5b6b1b80168d59371ba2b5313e6809a1208e16b9647d1ffd584ce8`).
- Construction audit: `D:\codex-runs\jev-information-density-v08b\selection-v08b-v04\factorial-bank-audit.json` (SHA-256 `c38c980aed9b231e1be15cc3ce5d42d67eff767f9b5b3286046fee7f97a778e`).

The factorial is not ready for LFM. Any further construction attempt needs a separately frozen solver amendment; it must not silently expand the 16-attempt search or relax the matching criteria.
