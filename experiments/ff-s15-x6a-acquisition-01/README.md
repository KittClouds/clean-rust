# X6-A: deficiency-guided acquisition (exploratory)

Question: can the structure of a partial graph say which fact to ask for next, at lower cost than random, confidence-based or broad-producer acquisition? Frozen X0 graph and controller, BANK-v1 DEV fold B, hidden slots, a costed `QUERY(slot)` API.

**Result:** preregistered rule CONTINUE (beats the best baseline at budgets 1-3 and on AUC at every hiding level); **attribution: schema closure, not graph inference.** A graph-free rule ("query empty-looking slots outside the GATE family") beats the preregistered best baseline by more than D does and beats D_full outright. Graph structure adds a small increment over it (0.015 AUC at h=0.3, n.s. at h=0.15) with a higher wrong-ACT rate. The controller's repair-set signal hurts. See `RESULTS.md`.

- `PLAN.md`: fixed before the first run (one amendment to policy C, before any run).
- `x6/`: `common.py`, `env.py` (slots, hiding, `Episode`, oracle selector), `policies.py` (A, B, C, D and its ablations).
- `run_x6a.py`: `run` (episodes), `analyze` (preregistered analysis, `results/x6a-receipt.json`), `explore` (post hoc controls, `results/x6a-explore.json`).
- `tools/make_results.py`: generates `RESULTS.md`, asserting every prose claim against the receipts.
- `tests/test_x6.py`: slot partition, hiding model, query API, stop rule, policy information limits, oracle minimality, frozen X0 hashes (14 tests).
- `evidence/` is git-ignored (per-world episodes).

Reproduce: `python run_x6a.py run && python run_x6a.py analyze && python run_x6a.py explore && python tools/make_results.py` (about 6 minutes; needs X1's `evidence/bundle.pkl`).
