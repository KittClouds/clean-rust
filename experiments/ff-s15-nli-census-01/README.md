# ff-s15-nli-census-01 — NLI-UNKNOWN oracle-headroom census

Follow-up to the ASK rung. Before building anything on NLI as independent evidence for ASK, this computes the impossible upper bound: does the frozen NLI head's `P(UNKNOWN)` identify a meaningfully different set of ASK cases
than the existing `P(ASK)`, or veto its false positives? No controller, no training, no policy change, CAL rows only.

- Plan (fixed before anything was computed): [PLAN.md](PLAN.md). Result: [RESULTS.md](RESULTS.md). Receipts: [results/census.json](results/census.json). Harvest draft: [HARVEST-ENTRY.md](HARVEST-ENTRY.md).
- **Outcome: the NLI route is dead at its ceiling.** A *perfect* NLI veto would lift ASK recall (at precision 0.5) by only 6.7% against a 25% bar; the real heads score AP 0.054–0.072 for ASK against a 4.9% prevalence (chance).
  BANK's NLI label is UNKNOWN for 83% of ASK rows but also 42% of ACT and 69% of ABSTAIN rows, and `P(ASK)`'s false positives are mostly ABSTAIN rows that NLI cannot separate from ASK.

## Run it

```bash
python run_census.py prepare   # ~4 min: re-verify Rung 0 hashes, rebuild the NLI heads on DEV (exact-match gate), read true NLI labels
python run_census.py census    # CAL only: sets, conjunction search, noise band, perfect-NLI ceiling -> results/census.json
python tools/make_results.py   # RESULTS.md from results/census.json (guards fail if a prose claim stops matching)
python -m unittest             # 10 tests on synthetic data with known answers
```

Depends on the ASK rung, C1 and C0 (imported unchanged), C1's verified `evidence/`, and the Rung 0 artifacts on `D:` (see C1's README). `evidence/` is git-ignored.
