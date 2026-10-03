# Harvest entry: X6-A deficiency-guided acquisition (draft, exploratory; no Harvest location found in the repo)

**FINDING**
With a frozen deterministic controller and hidden fact slots behind a costed query API, the graph-deficiency policy beat random, confidence and broad-producer acquisition on the recovery-cost frontier (AUC 0.478 vs 0.430 at 30% hidden; 3 of 3 budgets, all hiding levels). The gain is carried entirely by one signal, "which empty slots must hold facts" (slot completeness). A graph-free schema rule that only skips slot families that cannot be identified as missing beat D by 0.11 AUC; signal 3's increment over that rule is 0.015 AUC (0.010 to 0.020) at 30% hidden, not distinguishable from zero at 15%, and costs about one point of wrong-ACT rate. The controller's repair-set signal (what single fact would make the goal reachable) is a worse acquisition signal than random-among-plausible-empty, because a fact that would unblock the goal is not the fact that is missing.

**ENGINEERING PRINCIPLE**
Before crediting structure with an acquisition gain, give the flat baseline the schema's closure rules. Most of "deficiency-guided" acquisition was knowing which slots cannot be "missing", which a type rule supplies without a graph. Goal-blocking and missing-information are different questions.

**RECIPE**
Partition facts into slots; hide slots; cost every query including empty ones; stop at the controller's first ACT and score correct vs wrong; compare at matched cost to random, confidence, broad and oracle-selector; ablate each signal; then add the graph-free schema control.

**KNOWN COST**
BANK-v1 only: hiding cannot create conflicts (signal 2 never fired), requestability and per-slot cost are uniform, and the controller is deterministic. The schema control and the single-signal ablations were run after the first result and are labelled post hoc.

**DO NOT CLAIM**
That graph structure gives acquisition gains, or that it does not: the graph-specific increment is small and positive at high hiding. Nothing about learned or language-model acquisition, text, BANK-v2 or C-G1b.

**PRODUCT CONSEQUENCE**
Acquisition policies should start from schema closure rules and confidence; use graph deficiency only for what closure cannot give (incoming links, bridges). Do not route acquisition through the goal-repair set. Repeat on BANK-v2 (conflicts, requestability, cost) after V2-0 freezes its cue audit, with the schema rule as the baseline.

Evidence: `results/x6a-receipt.json`, `results/x6a-explore.json`, `RESULTS.md`, plan `PLAN.md`.
