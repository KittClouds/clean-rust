# BANK-v2 (`FF-S15-BANK-02`)

A new bank generation, built against a sealed constitution. **BANK-v1 is untouched** and remains a valid historical instrument for the question it was built to ask.

Question: given only what an agent can observe, under an explicitly declared information policy, can it determine, with a witness, what is true, what is next, what it may do, what it should ask for, and when it must decline or escalate?

## Read in this order

| file | what it is |
|---|---|
| [BANK-V2-FREEZE.md](BANK-V2-FREEZE.md) | the constitution (v0.7). Semantics are pinned here; code follows it, never the reverse |
| [bank-v2-objects.json](bank-v2-objects.json) + `.sha256` | its machine-readable companion and seal hash; `src/bank2/freeze.py` refuses to load on any mismatch |
| [lineage/](lineage/) | v0.5 and v0.6 archived byte for byte; `tools/check_freeze.py` re-hashes them |
| [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) | the staged plan and the choices the freeze left to implementation |
| [receipts/pilot-report.json](receipts/pilot-report.json) | the pilot receipt: 18 of 18 gates, every coverage requirement |
| [seed-registry-v2.json](seed-registry-v2.json) | the external seed registry (structure-only, zero rows imported) |

## What is in `src/bank2`

`freeze` (binds to the seal) · `facts`, `registry` (seven-predicate fact language, split-scoped relation registry) · `sim`, `refsim` (the simulator and an independent second implementation)
· `requirements` (the single evaluator behind `required_facts.query`: obligations, minimal-support alternatives, repairs, the four counterfactual checks)
· `algebra` (the §6 decision algebra, total and deterministic, with observation sufficiency) · `worldgen`, `intents` (a world is built toward a branch, then **the algebra derives the label**; a miss is regenerated, never relabeled)
· `targets` (seventeen targets, each with a witness that re-derives) · `render`, `lexicon` (8 seen plus 4 held renderer families with disjoint template pools) · `splits` (structural predicates, hash-partitioned held sets)
· `interventions` (P1 to P12 pairs) · `gates` (G01 to G18, each computed from data and self-tested with an injected defect) · `build` (pilot, full, seal).

## Run it

```bash
python tools/check_freeze.py            # the constitution's own consistency check (51 checks); --seal writes the sidecar
python -m unittest tests.test_stage123 tests.test_stage49    # 46 tests
cd src && python -m bank2.build pilot   # ~3 minutes, 5,794 rows, every gate
cd src && python -m bank2.build full    # post-dedup minimums: 725,000 canonical worlds, 800,000 rendered rows, 120,000 paired-panel pairs
cd src && python -m bank2.build seal    # writes BANK_v2_SEALED.json only if every gate passed and the accounting identity holds
```

## Sealed (2026-09-30)

`BANK_v2_SEALED = true` under constitution v0.7 (`receipts/BANK_v2_SEALED.json`): **18 of 18 gates PASS**, 725,000 canonical worlds (every split at its budget), **800,000 rendered rows** (`725,000 + 3 x 25,000`), 120,000 paired-panel pairs (10,000 per axis), 3.8 GB in 1,716 hashed shards under `out/full/` (git-ignored; `data/` for TRAIN and DEV, `public/test-inputs/` label-free, `protected/test-truth/` escrowed, `paired/`).
Every per-row gate ran on all 800,000 rows, including G02 (each row regenerated from its seed and compared). An independent consumer-side audit (`tools/audit_rows.py`) found zero duplicate world ids, every fact id equal to its content hash, and public inputs carrying no truth. `frozen_fabric_contact=false`, `system_1_5_training=false`, `terminal_truth_opened=false`, `external_rows_imported=0`.
Class shares over the whole bank: EXECUTE 30.0%, DECLINE_UNAVAILABLE 36.3%, ASK 14.4%, ESCALATE 14.3%, NOOP 5.0%; all sixteen reasons present (1.9% to 8.3%). The first full run failed G10 on 46 of 120,000 pairs (a same-property relation swap could duplicate a fact; one pair builder omitted a declared consequence); both were fixed in `interventions.py` and only the panels were regenerated, with the row-stage source hashes checked unchanged.

## What the build found (recorded in the freeze's amendment log)

Building against the freeze was itself an audit. v0.6 closed O11 (ruling C: requiredness at the obligation level, evidence at the fact level) and fixed five contradictions the verifier could not have caught by reading the prose: the reason-nullability rule contradicted the `ASK` and `ESCALATE` reasons; three reasons had no algebra step that could emit them; `OUT_OF_SCOPE` sat behind the plan search where `IMPOSSIBLE_GOAL` always pre-empted it; G17 demanded a non-requestability witness on declines it cannot apply to; and hiding a closed-slot fact would silently turn a true fact false.
v0.7 was written before the matching code when the generator first ran: `WAIT` is precondition-free so its `illegal` coverage cell could never fill (declared exemption, that cell only); a transitive relation requirement needs a target; opened `prohibited_edge` slots had no obligation source (decision dependence); reports, conflicts and uncertainty needed definitions; observation sufficiency became mechanical inside G03; worlds decided at step 1a record that the query was not evaluated.

## Legal boundaries (unchanged)

No frozen-LFM features, probe scores, adapters or downstream accuracy during construction. No selecting generators because a model likes them. Zero imported external rows. `terminal_truth_opened=false`: protected truth stays escrowed.
