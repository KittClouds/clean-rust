# Harvest entry — X1 non-oracle graph materialization (draft, exploratory; no Harvest location found in the repo)

**FINDING**
With a frozen controller and four heterogeneous producers (schema prior, lexical extractor, cached 230M edge-existence scores, synthetic noise with structured errors), arbitrating uncertain propositions as graph edges (per-relation calibration, agreement, functional slots, contradiction handling, slot and link completion) did not beat a calibrated logistic score merger at matched coverage and harm. It lost at low coverage in two settings (+0.8 points of harm at 21% coverage, mention-miss 0.2; +0.4 points, high synthetic noise) and was indistinguishable elsewhere. Multi-producer agreement is the only mechanism with a large effect, and the calibrated flat merger is the same sum of evidence. A better-behaved graph (fewer double locations) did not become a better decision.

**ENGINEERING PRINCIPLE**
A merger cannot supply a fact no producer proposed: coverage was capped by the producer that alone proposes switch states and gates, not by the arbitration. When a score merger is allowed to learn producer weights it already contains the evidence-combination that looks like "graph reasoning"; structure must add information the scores lack to earn its place.

**RECIPE**
Freeze the consumer, vary only the materializer; put every producer behind one ABI with no authority; compare against the strongest flat baseline (a learned weighted sum, not max or mean) at matched coverage and harm; ablate each structural mechanism; state the coverage levels only after checking what is reachable.

**KNOWN COST**
Exploratory. The lexical producer is a regular-expression extractor with a synthetic mention-miss factor; T2 is cached; the structure available to exploit in BANK-v1 is thin. The preregistered coverage levels were unreachable at the primary setting, so the preregistered test was degenerate there; the exploratory levels were chosen after seeing that.

**DO NOT CLAIM**
That graphs cannot help (BANK-v2's richer relation ecology is untested), that the 230M edge observer is useless (it adds existence evidence the flat merger also uses), or that this is a C-series result.

**PRODUCT CONSEQUENCE**
Do not build a graph arbiter on this evidence. Keep the graph as the controller's representation (X0) and fuse producer scores with a calibrated weighted sum. X5 (NLI as a producer) is not earned. V2-2 should ask first which decisions are deterministic graph readouts under perfect materialization, and treat graph-aware arbitration as a hypothesis with a lowered prior.

Evidence: `results/x1-receipt.json`, `results/x1-explore.json`, `RESULTS.md`, plan `PLAN.md`.
