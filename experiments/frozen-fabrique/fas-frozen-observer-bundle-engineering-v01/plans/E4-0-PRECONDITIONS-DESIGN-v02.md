# E4-0 Preconditions — Decision-Resolved Design v02

**Status:** planning draft, 2026-09-26. This records the user's six E4-0 decisions and the codebase-specific implementation details checked against E1/E2/E3. It is not a frozen contract, execution authorization, preflight result, or receipt. No population has been generated; no tokenizer/model contact, label opening, scoring, fitting, or serving measurement follows from this document.

**Supersession:** v02 supersedes the unresolved-decision list in E4-0-PRECONDITIONS-DESIGN-v01.md. The pinned proposal and E4-CODEBASE-MAP-v01.md remain unchanged.

## Bound starting identities

| Artifact | Bound identity |
| --- | --- |
| E0 v10 | 899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd |
| E1 v04 population | 6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03 |
| E1 context/entity term inventory | SHA-256 43b793068ad759a7ec77bd0027e7113a0145a35b1daacb8ea1cefa551803c672 |
| E2 v07 feature cache | a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a |
| E3 v02 observer bundle | 899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1 |
| E3 v02 score and independent replay | a104bffedbc3e31268c0f1c0103ad4326add5a9da93816007904b70cdf3c7d1f |

E3's eight endpoint gates passed individually. E3 did not make a simultaneous 95% bundle claim, and its E1 TEST population is spent. E4-0 uses new terminal data and a familywise-adjusted lower-bound rule.

## E4-0 result and gate order

E4-0 has three required results, in order:

1. A fresh E4 population, including frozen held-out template material, is constructed, support-audited, and sealed before any E4 model contact.
2. The qualified online feature path reproduces the cached E1 FIT features and all five E3 head predictions on a label-free parity panel.
3. The five frozen E3 heads pass all eight simultaneous fresh-data endpoints on E4's seen-template population.

Every gate must pass for the simultaneous bundle qualification claim. Preserve the attempt and stop at the first failed gate. A completed E4-0 does not execute E4-A.

## Lock 1 — Fresh population identity

**Preserve the E1 term inventory byte-for-byte.** The 32 context IDs and 32 entity IDs retain their exact E1 ID-to-term mappings because the frozen E3 identity observers output those IDs. A new lexical/world seed must not reassign those meanings.

Use a new population namespace and a new deterministic world/render seed stream. The E4 namespace participates in quartet-ID derivation; row IDs derive from the namespaced quartet ID and variant ID. Freshness is checked independently at three levels:

- Quartet IDs are disjoint from E1 and unique within E4.
- Row IDs are disjoint from E1 and unique within E4.
- Rendered-input SHA-256 values are disjoint from E1 and unique within E4.

Candidate generation uses a domain-separated namespaced seed stream and an increasing candidate counter. If any candidate quartet or one of its rows collides at any of the three levels, reject the entire quartet, increment the counter, and regenerate. Record each rejected counter and collision class in the construction receipt. Do not silently deduplicate or retain part of a quartet.

The generator freezes one deterministic schedule before materialization. It must retain all four rows of every quartet in one population stratum and one truth-access partition. New IDs alone do not count as fresh content.

## Lock 2 — Held-out templates and truth boundary

Create genuinely new observation and query template strings. Freeze their exact UTF-8 bytes and hashes, normalized forms, placeholder schema, and semantic-role audit before generating any E4 rows. The normalized-text exclusion rule is Unicode NFKC, Unicode case-folding, trimming, and collapsing each run of whitespace to one ASCII space. Require both exact-byte and normalized-form nonmembership against every E1 template and every template used by fitting material.

The template audit must confirm that the new wording preserves the registered semantic slots and that placeholders cannot encode target labels or class IDs. E1's historical HELDOUT style-role string does not satisfy this requirement.

The current candidate bytes are recorded in E4-0-HELDOUT-TEMPLATES-v01.json (SHA-256 ae8c5c29c7ed29d644e88c19d6baffa4476ec2f4c5f17aee89801fd44c72eb57). The author-side text audit is in E4-0-HELDOUT-TEMPLATES-v01-audit.json: E1 source identity matches, exact and normalized collision counts are zero, and all slot-count checks pass. Independent semantic/template audit is still required before these candidates are bound into the E4-0 contract.

Construct and seal the held-out-template stratum and the joint template-plus-lexical stratum. Their label files remain escrowed. They may receive frozen-ABI feature extraction if the resource preflight includes them, but E4-0 does not open their truth, emit class-support tables, score them, or inspect predictions. The first template truth access waits until FF-BUNDLE-TEMPLATE-01 has its own analysis contract frozen. The joint stratum follows the same truth boundary.

## Lock 3 — Primary population support and size

The primary fresh population contains the E1-template seen-rendering rows and the three lexical novelty strata: context-novel, entity-novel, and both-novel. Novelty uses E3's frozen FIT-term definitions and the preserved E1 term-ID mapping.

Retain E3's eight endpoint definitions and eligibility rules:

| Frozen order | Endpoint | E4 primary rows |
| --- | --- | --- |
| 1 | context_identity | All eligible seen-template primary rows |
| 2 | entity_identity | All eligible seen-template primary rows |
| 3 | relation | Both-terms-train-side rows, as in E3 |
| 4 | observed_state | Both-terms-train-side rows, as in E3 |
| 5 | exact_target_in_domain | In-domain lexical rows |
| 6 | exact_target_context_novel | Context-novel lexical rows |
| 7 | exact_target_entity_novel | Entity-novel lexical rows |
| 8 | exact_target_both_novel | Both-novel lexical rows |

Use the deterministic generator support schedule to choose the smallest whole-quartet prefix for which every registered endpoint has at least **250 rows per required truth class** after its eligibility filter. This is a 25% construction buffer over the unchanged **200 rows/class scoring floor**. The pre-model support receipt reports every class count for the eight primary endpoints. A panel that meets 250/class at construction but falls below 200/class in the sealed evaluation support audit stops before model contact.

Include the joint template-plus-lexical stratum in the intended E4 population. Its inclusion is conditional only on the prospective storage/resource preflight passing with the frozen reserve. If it does not fit, preserve the preflight and revise the design before generation; do not quietly omit it or use post-score cost to decide.

Resource estimates count 8,192 bytes per float32 feature row (2,048 dimensions), plus row/label manifests, hashes, staging copies, observer artifacts, temporary files, and the frozen free-space reserve. A GPU lease and process-scoped resource receipt are required before any eventual model contact.

## Lock 4 — Online/cache parity

The binding configuration is exactly the qualified E2 v07 ABI: CUDA:0, float32, batch 1, no padding or truncation, final unpadded token from last_hidden_state. Batching and other device paths are outside E4-0 and belong to a separately frozen E4-A serving study.

Use **256 whole quartets** selected deterministically from E1 FIT. Compute token lengths with the pinned E2 tokenizer using add_special_tokens=true, truncation=false, and no padding, then assign each quartet to a token-length quartile using the maximum token count among its four variants. Sort E1 FIT quartets by (maximum token count, UTF-8 quartet ID); for N quartets and zero-based rank r, quartile k is the unique value in 0..3 satisfying floor(k*N/4) <= r < floor((k+1)*N/4). Within each of the 8 query-template IDs × 4 quartile cells, rank candidates by the raw SHA-256 digest bytes of this byte string: UTF-8("FAS-E4-0-PARITY-v01") || 0x00 || ASCII decimal query-template ID (no leading zero) || 0x00 || ASCII decimal quartile ID (no leading zero) || 0x00 || UTF-8 quartet ID. Break digest ties by UTF-8 quartet ID bytes and choose the 8 lowest-ranked quartets per cell. This yields 256 whole quartets and guarantees template and length coverage. The selected row IDs and token lengths are sealed in a label-free parity-panel receipt before online feature extraction. If any cell contains fewer than 8 eligible quartets, stop before model weights load and version the design; do not relax the selection after observing parity.

On this panel require:

- byte-for-byte equality between online float32 feature rows and the corresponding sealed E2 cache rows;
- 100% predicted class-ID agreement for each of the five unchanged E3 heads;
- ordered E1 row identity, shape, dtype, finiteness, and per-head prediction receipts.

There is no epsilon for this exact same-device, same-ABI path. Report maximum absolute deviation as a diagnostic; the binding feature gate is zero differing bytes. E0's standalone/bundle logit parity (atol=rtol=1e-6) remains a separate invariant.

## Lock 5 — Simultaneous fresh qualification

Do not refit or modify the five E3 observers. On the E4 primary population, preserve E3's balanced-accuracy metric, class support rule, whole-quartet class-stratified bootstrap, and 0.90 floor. Change only the familywise confidence allocation:

    alpha_i = 0.05 / 8 = 0.00625
    pass_i  = np.quantile(bootstrap_BA_i, 0.00625, method="linear") >= 0.90
    bundle_pass = all(pass_i for the eight frozen endpoints)

Use 10,000 replicates, preserving E3's bootstrap mechanics: NumPy PCG64, one generator consumed in frozen endpoint order, resample complete quartets within each task's truth-class stratum using E3's A-variant quartet label for that task, retain the 64-replicate chunking, and use NumPy's linear quantile method. Freeze the fresh fixed RNG seed as 2026092604 and the endpoint order above before any E4 labels are opened.

The independent auditor replays the saved predictions and bootstrap outputs. All eight lower bounds must reach 0.90 for the simultaneous bundle claim. Report every endpoint. A failed endpoint is not dropped, rescued, or rerun under this identity. Held-out-template and joint-stratum predictions and labels are not part of these eight endpoints.

## Lock 6 — Fit data and truth access

E1 FIT is the designated fit material for later companion analyses, including matched R1-style comparators, feature-source attribution heads, and fit-variance work. Those analyses need their own contracts and execution identities.

No fresh E4 primary evaluation label may enter fitting, observer selection, or threshold selection. No held-out-template or joint-stratum truth is opened before FF-BUNDLE-TEMPLATE-01 freezes its analysis contract. E4-0 itself performs no fitting.

## E4-A dependency

Normal E4-A capability-fabric routing and serving-economics work is eligible for a separate design only when online/cache parity and all eight simultaneous E4-0 endpoints pass. If parity passes but fresh qualification fails, do not run normal E4-A. A systems-only sharing-cost microbenchmark may be proposed later under a distinct identity and explicit interpretation; it cannot support a qualified capability-fabric serving claim.

## One phase at a time

The next artifact is a machine-readable E4-0 design/contract draft that binds the above decisions, exact population and template sources, support schedule, parity selection algorithm, E3 observer hashes, bootstrap seed and code, resource envelope, label-access partitions, and stop receipts. Review and seal that contract before the model-free population construction phase. Audit the sealed population before any model/tokenizer contact. Parity precedes fresh qualification. E4-A and both companion studies remain separate later decisions.
