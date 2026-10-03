# v0.8I Phase A v02-Clean

**Identity:** `phase-a-v02-clean`  
**State:** Phase A construction and independent validation PASS; Phase B remains unauthorized.  
**Contract:** [`phase-a-v02-clean-contract.json`](../experiments/jev-information-density-v08i/phase-a-v02-clean-contract.json)

## Disposition of v01

`phase-a-v01` is permanently quarantined as `NONPROMOTABLE_BOUNDARY_BREACH`. Its
semantic construction outputs remain provenance/regression material only. No
v01 S100/F100 bank, selected certificate, or representation table may parent,
seed, or be copied into v02. The supplemental boundary audit supersedes v01's
original no-evaluation-read claims.

## Frozen scientific design

V02 preserves the v0.8I Phase-A semantics and all declared values:

- exact-world generator seed `20260921`;
- 12 training families and 4 held-out families, with family/template separation;
- 1,000 training pairs per training family and 500 held-out pairs per held-out
  family (12,000 / 2,000 pairs; 36,000 / 6,000 episodes);
- 5,000 training anchors selected with the frozen family-balanced hash rule;
- 100,000 groups per arm, with a 90,000-row common skeleton and 10,000
  replacement rows per arm;
- unchanged S100/F100 contrast semantics, frozen training-signature function,
  and expected `D_train = 0.05`;
- unchanged eligibility, protected-data, and Phase-A acceptance criteria.

The only change is source-materialization machinery. There is no model load,
feature extraction, training, evaluation inference, or Phoenix access.

## Training-only representation scope

The v02 representation tables are built from canonical episodes referenced by
the sealed `R100-star` training group manifest. The v0.8G mixed-scope text tables
are not opened. Before canonical extraction, the builder checks R100-star IDs,
episode/root/family identities, and available exact text, schema-surface, and
model-input fingerprints against protected metadata. Protected evaluation
content is not parsed to perform these checks.

The canonical archive is a shared source file. Its early identity prefix is used
to locate requested training episodes; only matching R100-star episode records
are JSON-decoded and materialized. Nonmatching record tails are skipped without
JSON decoding or output. The receipt records this scan mode and counts. Every
resulting group/table receipt is bound to the `R100-star` manifest hash, source
row count, and group-ID digest.

The assembler verifies every table's training-only certificate before opening
the table, reconciles the complete source group-ID digest, and reads only the
generated training certificates and selected training episode bodies. It uses
generator receipt metadata for held-out family/template/episode identity checks;
generated held-out body files remain unopened.

## v02 result

The fresh identity completed Phase A without model contact:

- generator: 12,000 training pairs / 2,000 held-out pairs;
- representation scope: 100,000 R100-star training rows, 8,599 states, and
  zero protected group, episode, root, family, exact-text, schema-surface, or
  model-input overlaps;
- supplemental metadata-only fingerprint audit: zero overlap across all 16
  available keys, including semantic, structural, gold-target,
  generator/definition-template, schema-composition, intervention, family,
  exact-text, schema-surface, and model-input fingerprints;
- scope scan: 69,394 selected training episode bodies parsed, zero protected
  evaluation bodies parsed, and zero nonselected archive bodies JSON-decoded;
- exact-world independent validation: all 36,000 training episodes passed the
  exact solver;
- independent contrast audit: all 5,000 selected triplets passed identity,
  schema, single-edit, exact-posterior, winner-flip, and sham-invariance checks;
- banks: 100,000 groups each, 90,000 identical common-skeleton rows, matched
  exposure profiles, and independently recomputed `D_train = 0.05`.

The independent reports are stored under
`D:/codex-runs/jev-information-density-v08i/phase-a-v02-clean/materialized/`:
`phase-a-v02-independent-audit.json` and
`phase-a-v02-exact-world-train-audit.json`. The constructor receipts are
`phase-a-bank-receipt.json` and `phase-a-integrity-receipt.json`.
The supplemental fingerprint audit is
`phase-a-v02-extra-fingerprint-audit.json` (SHA-256
`cc3368017175bef9b9e3fb3930660fdc43b18e699f660229eac80212316d7f7d`). It
compared training-only metadata with protected NewTight and legacy identity
manifests; all 16 available overlap-key classes were zero, and no protected
evaluation or canonical evaluation bodies were opened.

The v01 identity remains quarantined and was not used as a source for v02.
Several v02 preflight/assembly attempts were preserved under separate
`phase-a-v02-contract-stale-*` directories; they are not parents of the
promotable v02 banks.

A read-only post-run hash check confirmed that v01's bank receipt, integrity
receipt, and all files listed by its bank receipt still match their sealed
hashes.

## Promotion boundary

Phase A passed exact-world validation, family/template/episode separation,
protected identity/fingerprint firewall checks, source-scope certification,
bank/profile matching, and independent training-signature reconciliation. This
does not authorize Phase B. Model contact requires a separate user
authorization after review of the clean v02 artifacts.
