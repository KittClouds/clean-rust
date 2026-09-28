# v0.8 Preselection Amendment: Model-Input Redundancy

**Status:** frozen before R100/C100 selection and before any model contact.

**Amendment lineage:** this document records the first C100 update (`v1.1`); the final selected policy is `C100-v1.2-static-frequency-coverage`, specified in [the selection-engineering amendment](jev-information-density-v0.8-selection-amendment.md).

## Trigger

The full v0.8 generator passed exact target consistency and cross-language signature checks, but the 500,000 atomic groups contained only 30,956 unique normalized model-visible input signatures. There were 469,044 repeated occurrences; every repeated signature had one exact gold signature (`max_gold_signatures_per_input = 1`). This is a generator-side structure audit, not a model result.

The original C100 redundancy features tracked root, semantic/structural, and observation-level novelty but did not directly track whether the complete exposed state/query/candidate input had already been selected. A different root or internal semantic fingerprint could therefore appear novel to the curator while the model-facing input was identical.

## Normative change

Only the C100 redundancy feature set changes. The selector derives the unique `model_input:` digest already present in each immutable group record and adds it as a redundancy feature. The five coverage axes and greedy score remain equally weighted; R100's stratification and seed are unchanged. C100 uses seed `jev-idv08-c100-sha256-v2-input-redundancy` and policy ID `C100-v1.1-input-redundancy`.

The amended C100 policy is hashed before selection. No model predictions, embeddings, protected evaluation labels/scores, or post-selection behavior informed this change. The generator output and all legacy sources remain unchanged.

## Interpretation boundary

The 300,000 minimum remains a count of eligible atomic groups, not distinct model-visible inputs. Reports must publish both counts and may not call the universe 300,000-input-overcomplete. R100 and C100 remain exact 100,000-group matched selections from the same eligible universe; C100 may still contain repeated inputs because the target group count exceeds available unique input signatures. The amount of repeated exposure in each bank is a required information-density statistic.
