# Harvest entry — C2a (draft; no Harvest location was found in the repo, so it lives here until you place it)

**FINDING**
Multiple Rung-0 surfaces from one frozen 230M backbone provide little oracle headroom for safe action routing at the primary harm operating point, and they share harmful errors.
At α = 0.05 on CAL the primary surface correctly executes 740 actions; an oracle that picks the right one of four surfaces on every row reaches only 853 (+15.3%, bar 25%).
Of the primary's 28 harmful executions, `final_plus_mean` also says ACT on 28, `layer_m4_final` on 26, and the supposed abstention specialist `full_mean` on 26, with median P(ABSTAIN) of 6–13%.

**ENGINEERING PRINCIPLE**
Surface diversity is not evidence diversity. Coordination pays only when observers have meaningfully different failure modes.

**RECIPE**
Before building an ensemble or a coordination controller, compute its impossible upper bound first ("oracle headroom before controller"):
safe-set overlap, oracle union headroom, shared harmful errors, veto power, and the matched-harm frontier of the single-surface baseline. It takes minutes, uses vectors you already have, and needs no backbone run.

**KNOWN COST**
At looser harm targets the oracle headroom rises (α = 0.10: +35%), but it stays an oracle bound and is paid for in harm; it does not establish a realizable controller.

**DO NOT CLAIM**
That the surfaces are globally redundant. They remain differentiated on NLI, abstention, graph composition and other tasks; this finding is about safe-ACT routing only. Also not claimed: anything confirmatory — this is DEV evidence.

**PRODUCT CONSEQUENCE**
Do not build C2b over these four surfaces. Seek task-specialized or otherwise independent observers (for ASK: NER, NLI, a dedicated ASK head).

**METHOD LESSON (general rule)**
Judge routing improvements at matched harm on the frontier, C_new(H) > C_baseline(H), never against a single baseline operating point at a different harm: a single surface reaches +24% coverage at 6.5% harm just by loosening its threshold.

Evidence: `results/c2a-census.json`, `C2A-RESULTS.md`, plan `C2A-PLAN.md` (written before the census).
