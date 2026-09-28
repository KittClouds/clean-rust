# E4-0 Preconditions — Codebase Design Note v01

**Status:** draft planning note, 2026-09-26. This narrows the [pinned E4 map](E4-CODEBASE-MAP-v01.md) to E4-0. It is not a frozen contract, authorization, preflight result, or execution receipt. The [source proposal](e4-proposal-source-v01.md) supplies the three required outcomes: a fresh sealed population, online/cache parity, and simultaneous fresh qualification. E4-A and companion analyses remain later decisions.

## The three E4-0 results and their order

| Gate | Required evidence | Stop point |
| --- | --- | --- |
| Fresh population | New population identity, sealed templates, disjoint row/quartet/content identities, whole-quartet strata, label isolation, support and resource receipts, independent seal audit. | No model contact until the population and its sources pass. |
| Online/cache parity | Online features on a preselected, label-free E1 FIT panel compared with the sealed E2 cache; maximum absolute deviation, all five head predictions, configuration/resource receipts, and independent replay. | A failed intended serving configuration stops before fresh qualification. |
| Fresh qualification | Five unchanged E3 heads scored once on the new seen-rendering and lexical strata; eight balanced-accuracy endpoints with whole-quartet bootstrap lower bounds and a familywise 95% Bonferroni rule; independent replay. | Any failed endpoint closes the simultaneous bundle claim for this version. |

Passing all three makes E4-A eligible for a separate design and decision. It does not itself perform or authorize dispatch, request routing, serving economics, or the two companion studies.

## Population construction from the actual E1 generator

The E1 generator is deterministic and hardcodes `GENERATOR_SEED = 2026092501`, eight observation templates, eight query templates, and a factorial schedule. Its term inventory assignment depends on that seed. The sealed E1 [term inventory](<D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04\corpus\term-inventory-v01.json>) is 1,412 bytes, SHA-256 `43b793068ad759a7ec77bd0027e7113a0145a35b1daacb8ea1cefa551803c672`.

The E3 context/entity heads predict those exact 32 class IDs in each role. E4-0 therefore has to hold the E1 ID-to-term tables fixed while giving world/render sampling a separate new namespaced seed. The existing `quartet_id` hash does not include a population seed; each row ID is `quartet_id:variant_id`. The E4 generator must put the new population namespace into those identities. It must also show that new input-text SHA-256 values do not duplicate E1 rows. A deterministic collision/skip rule belongs in the future contract; a new seed or new ID by itself does not prove fresh content.

All eight E1 query templates are traversed by the generator, and E1 splits by whole quartet rather than by template. The historical `HELDOUT` style-role string for IDs 6–7 is not a template holdout from E3 fitting. The E4 held-out template set needs new template strings, frozen and hashed before generation, with an explicit exact-text and normalized-text exclusion check against E1 and any fit. Seen-rendering rows continue to use E1 template text with new semantic items.

The E4 population contract should separate: (1) seen-rendering and the three lexical target-novelty strata for the eight primary endpoints; (2) newly held-out templates for descriptive and later matched analysis; and (3) joint template-plus-lexical rows if the prospective support and storage budget permits. Every four-variant quartet stays in one stratum/partition. The class labels and target class meanings stay those of E1. E4-0 does not fit a new head.

The proposal says the held-out-template stratum is descriptive during E4-0, while `FF-BUNDLE-TEMPLATE-01` owns its primary analysis. Before any template labels are opened, either freeze that branch's primary contrast or defer the descriptive label opening. Otherwise the shared terminal template population would be revealed before its primary analysis is fixed. This is an E4-0 population/truth-access decision, even though companion execution is later.

## Online/cache parity from the actual E2 and E3 code

E1 v04 has `FIT` and `TEST`, with no separately sealed validation split. E3 fitted on FIT. Parity is a computation check with no truth labels, so a preselected panel of E1 FIT row IDs is the code-compatible interpretation of the proposal's “train/validation rows.” The frozen E1 TEST labels and scored-row artifact play no role.

The canonical path is the pinned `V1_FINAL_POSITION` ABI: same model/tokenizer revision, runtime, CUDA:0, float32, batch 1, no padding/truncation, and the final unpadded `last_hidden_state` vector. A new online adapter must load the model and the E3 head files read-only, preserve the exact tokenization/forward/readout order, and bind its own source hash. E2's one-shot extractor and cache remain unchanged.

Before running parity, freeze the FIT row-selection algorithm, intended serving configurations, numerical tolerance `ε`, and output comparison. A strict proposed baseline is byte equality for the same-device batch-1 path because E2 v07 reproduced its registered repeat rows exactly. Any added batch or device path needs its own prospective tolerance; padding and final-token indexing cannot be inferred from the batch-1 ABI. For every intended configuration, require 100% per-head class prediction agreement and report the maximum absolute feature deviation. Existing E0 standalone/bundle logit tolerance (`atol=rtol=1e-6`) concerns identical feature rows and is a separate check.

## Fresh simultaneous qualification

The eight endpoints retain E3's meanings: 32-class context identity, 32-class entity identity, relation and state on the both-train-side term subset, and exact target on in-domain, context-novel, entity-novel, and both-novel lexical slices. Lexical novelty is relative to the target head's FIT terms; target classes remain fitted. The five E3 scaler/weight/bias sets are read-only and hash-checked against the sealed bundle manifest.

Keep balanced accuracy, whole-quartet class-stratified resampling, the 0.90 floor, and the prospective per-class support rule. The proposed simultaneous 95% statement applies a one-sided lower quantile of `α_i = 0.05 / 8 = 0.00625` to each of eight endpoints, then requires every bound to reach 0.90. E3's scorer currently uses a `0.05` quantile and E1 TEST paths, so E4 needs a new versioned scorer and independent auditor. The replicate count, RNG seed/stream, quantile method, and support-sized population must be fixed before scores are seen. The held-out-template rows are outside this eight-endpoint gate.

The fresh score should retain all per-head predictions, class support, bootstrap arrays, gate decisions, and a terminal disposition. The independent auditor should replay them from the sealed scored artifact without reopening raw terminal labels.

## Decisions to bind before an E4-0 freeze

1. New item schedule and population namespace while retaining the E1 term inventory; exact collision rule against E1 quartet, row, and input hashes.
2. Exact new held-out template strings and hash, plus the semantic/placeholder checks that keep labels comparable.
3. Quartet counts per primary and template stratum, per-class support floor, optional joint stratum, cache size (`8,192 × feature rows` bytes), staging allowance, and disk/GPU reserve.
4. E1 FIT parity-panel selection and size; intended device/batch paths; prospective `ε`; whether same-device batch-1 byte equality is the binding primary check.
5. Bonferroni bootstrap replicate count, fresh seed, lower-quantile rule, and any decision to retain E3's 200-row per-class minimum.
6. Template truth-access order and whether attribution later trains on E1 FIT or a separate fresh FIT/DEV partition. These choices determine the E4-0 population layout but do not authorize companion execution.

## One phase at a time

The next artifact is a machine-readable **E4-0 design draft** resolving those six items and identifying the exact new generator, online adapter, scorer, auditor, and source hashes. Only after review would E4-0 panel construction receive a versioned execution identity. Panel audit precedes any model contact; parity precedes fresh qualification; E4-A remains a separate later phase.
