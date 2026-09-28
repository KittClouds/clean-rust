# JEV Q-X1: Boundary Geometry Diagnostic

**Disposition:** exploratory, post-hoc, read-only analysis of sealed v0.8Q predictions. This does not amend Q's registered labels, thresholds, or result, and it is not a new training or evaluation run.

## Question

Do the sharply different SHAM-LOW MAP outcomes line up with the neighborhoods' starting position relative to the old/new decision boundary?

## Method and limits

The diagnostic re-read all 408,000 rows of the sealed raw prediction file, verified its SHA-256, and analyzed the 96,000 step-120 rows (24,000 neighborhood rows: 3 seeds × 4 arms × 2,000 neighborhoods). It used exact `old_candidate_id` / `new_candidate_id` identities to recover candidate probabilities from the serialized semantic-ID vector. All four views were required for each neighborhood; family quotas were checked at 500 per family, and the reconstructed fact-winner, anchor-winner, locality, and new-candidate movement summaries matched the frozen Q analysis in all 12 seed × arm cells within `1e-6`.

The available output is **probabilities, not logits**. Define the pairwise probability margin

`m = P(new candidate) - P(old candidate)`.

`m = 0` is a tie between those two candidates only. It is not the full four-class decision boundary: either of the other two candidates can still be the MAP winner. Therefore actual crossings below always mean `argmax(P_fact) == new_candidate_id`; pairwise margin and MAP crossing are reported separately. No margin threshold was added to Q.

For each head, the fact-conditioned movement in this margin is

`m_fact - m_anchor = [P_new(F)-P_new(A)] - [P_old(F)-P_old(A)]`.

This separates movement of the desired new candidate from movement of the old candidate. The comparison is descriptive across separately trained heads; it is not a within-head intervention on a fixed parameter state.

## Step-120 results

| Seed | LOW−SHAM change in new-candidate movement | LOW−SHAM change in old-candidate movement | Mean `m_anchor`, SHAM → LOW | Mean `m_fact`, SHAM → LOW | Mean fact margin movement, SHAM → LOW |
|---|---:|---:|---:|---:|---:|
| 2540205348 | +0.0608 | −0.0697 | −0.1792 → −0.3555 | −0.0949 → −0.1407 | +0.0844 → +0.2148 |
| 2603246505 | +0.0002 | −0.0062 | −0.1041 → −0.0529 | −0.0721 → −0.0145 | +0.0320 → +0.0384 |
| 3565067208 | +0.1046 | −0.1069 | −0.0739 → −0.1821 | −0.0441 → +0.0593 | +0.0298 → +0.2414 |

The corresponding SHAM-LOW fact-new MAP rates were **0.00%, 16.35%, and 69.05%**. Anchor old-winner preservation was **100.00%, 78.35%, and 99.95%**.

| Seed | LOW sham L1 vs DUP | LOW matched L1 vs DUP | LOW fact margin ≥ 0 | LOW actual fact-new MAP |
|---|---:|---:|---:|---:|
| 2540205348 | 0.0711 vs 0.1797 | 0.0442 vs 0.1055 | 0.40% | 0.00% |
| 2603246505 | 0.0144 vs 0.1578 | 0.0069 vs 0.0978 | 16.60% | 16.35% |
| 3565067208 | 0.0831 vs 0.0430 | 0.0464 vs 0.0262 | 80.00% | 69.05% |

Seed 3 had 219 neighborhoods where the new-vs-old pairwise margin was nonnegative but the new candidate was not the four-way MAP winner. Seed 2 had five such cases; seed 1 had eight. This is why a pairwise margin is a useful diagnostic, not a substitute for the registered crossing metric.

## What the boundary view clarifies

**Seed 2540205348 — response moved, but began too far away.** SHAM-LOW increased new-candidate fact movement over SHAM by `0.0608` and made the old candidate fall by an additional `0.0697`; together, the mean within-head pairwise margin movement rose from `0.0844` to `0.2148`. Yet the SHAM-LOW anchor margin was much more negative (`−0.3555` versus `−0.1792`), and its mean fact margin remained negative (`−0.1407`). No new candidate became MAP. This directly illustrates why increased target-probability movement does not guarantee a boundary crossing.

**Seed 2603246505 — a near-boundary, family-concentrated crossing plus a separate preservation failure.** New-candidate movement changed by only `+0.0002` on average, but SHAM-LOW moved the mean anchor pairwise margin closer to zero (`−0.0529` versus `−0.1041`). The `327/500` respiratory neighborhoods that crossed had mean SHAM-LOW anchor margin `−0.0280`, versus `−0.0304` among the 173 that did not. Under the SHAM-trained head, their fact margins were also somewhat closer to zero (`−0.0449` versus `−0.0496`). SHAM-LOW respiratory fact margins averaged `+0.0039` among crossers and `−0.0030` among noncrossers. All 327 new-winner crossings were respiratory (`65.4%` of that family); none occurred in the other families. Separately, vibration anchor preservation fell from `99.8%` under SHAM to `13.4%` under SHAM-LOW, while vibration fact-new MAP remained zero. Boundary proximity helps explain the respiratory threshold crossings, but not the collateral vibration failure.

**Seed 3565067208 — large margin movement overcame a farther starting point, while locality failed.** SHAM-LOW's anchor margin was more negative than SHAM's (`−0.1821` versus `−0.0739`), but its fact-conditioned pairwise margin movement rose from `0.0298` to `0.2414`; mean fact margin moved from `−0.0441` to `+0.0593`, and `69.05%` became new-candidate MAP winners. Within exposure, crossers began somewhat closer to zero than noncrossers (`−0.1659` versus `−0.1924`) and ended with mean fact margins `+0.0468` versus `+0.0038`. Crossers and noncrossers both had elevated SHAM-LOW locality errors: sham L1 `0.0716` vs `0.0651`, matched L1 `0.0339` vs `0.0310`. At the arm level, both LOW locality metrics were worse than DUP (`0.0831 > 0.0430`; `0.0464 > 0.0262`).

## Interpretation

Boundary position is a real missing coordinate, but it is **not a complete explanation** of Q's seed differences. It makes the seed-1/seed-2 contrast intelligible: seed 1 had a larger response-margin shift but started substantially farther from the old/new tie; seed 2 started closer and crossed a narrow respiratory subset with almost no average gain change. Seed 3 crossed broadly because its fact-conditioned margin movement was much larger, despite a more negative anchor margin than seed 2.

The result is therefore not “crossings are just baseline margin.” The observed MAP pattern reflects at least the combination of starting margin, fact-conditioned margin movement, competition from the other two candidates, and family-specific preservation. The vibration loss in seed 2 is particularly clear evidence that one old/new boundary coordinate cannot summarize collateral behavior.

This strengthens the descriptive conclusion that response gain, pairwise margin movement, four-way crossing, locality, and anchor preservation vary separately. It does **not** establish an optimizer basin, causal mechanism, population frequency, or a universal boundary law. Q's registered same-seed labels remain unchanged.

## Direction for the next study

Do not dose-sweep or tune from these outcomes. The discriminating next step is a fresh-world, larger paired-seed replication of the **same** four-arm Q design and the same `0.5×` SHAM-LOW weight. Add the probability pairwise margins, actual multiclass crossings, and family-level preservation as predeclared measurements. Classify response phenotypes per seed; do not assemble gain and locality passes across different seeds. Treat respiratory crossing with vibration preservation loss as a secondary replication question, not a reason to modify the intervention.

Eight or twelve fixed paired seeds would be more informative than another three if compute permits, but choose and seal the seed set before execution. This is a recommendation for a new protocol, not authorization to train it.

## Provenance

- Sealed predictions: `D:\codex-runs\jev-information-density-v08q-run-v01\evaluation-continuation-v01\raw-predictions-v01.jsonl`, SHA-256 `d4bc4fce5fd1c51815ac214b794e3b5d5c51f549d80ad7e1362ec5c04abc976e`.
- Frozen Q analysis used only as a parity reference: `q-response-analysis-v01.json`, SHA-256 `403994de956e96c7ff2809fc8c255f9cd3fdadfcc0b270eb3b5a30306e38901e`.
- Q-X1 final outputs: `D:\codex-runs\jev-information-density-v08q-run-v01\q-x1-boundary-geometry-final-v01\`.
- Per-neighborhood CSV SHA-256: `db98c31de937dc466bbdce67e0292438151da45bf093d85c52bdded1aaf1290a`.
- Summary JSON SHA-256: `67570c4d729a9feb20b80230d347e86dcf0adfea985c8b5fe5ca73affc852de3`.
- Q-X1 source: `experiments/jev-information-density-v08q/source/q_x1_boundary_geometry_v01.py`.
- No model/head was loaded; no training, inference, panel access, or changes to sealed Q artifacts occurred.
- Two earlier same-turn diagnostic outputs were development passes superseded by the final parity-checked run; this report binds only to the `q-x1-boundary-geometry-final-v01` receipt and outputs.
