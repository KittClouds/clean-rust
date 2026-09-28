# v0.8 C100 Selection-Engine Amendment

**Status:** frozen before either R100 or C100 manifest was emitted and before model contact.

## Trigger

The first full-pool implementation of exact dynamic lazy-greedy coverage ranking processed a 416,672-group eligible pool. It consumed more than ten CPU minutes without emitting selected IDs. The completed preselection, firewall, and family-split receipts were preserved in the first selection-run directory; that run emitted no R100/C100 IDs and is not a result.

The issue was computational cost from repeatedly refreshing stale candidate scores when common metadata features changed. Continuing that implementation offered no methodological advantage worth an unbounded local runtime for this bounded data-construction slice.

## Normative change

The final C100 policy is `C100-v1.2-static-frequency-coverage`, with seed `jev-idv08-c100-sha256-v3-static-frequency-coverage`. It retains the five equally weighted metadata axes and includes the normalized model-input digest in the redundancy axis. For each eligible training group, calculate the mean across axes of the mean `1/sqrt(eligible_pool_count(feature))` over its features. Select the exact top 100,000 groups, breaking ties by ascending `SHA256(seed || group_id)` and then lexical group ID.

This is a one-pass global rarity-weighted coverage ranking, **not** dynamic greedy selection. It is deterministic and costs one score calculation per eligible group plus bounded top-k ranking. R100's stratified-random procedure and seed are unchanged. The amended contract and selector source are hashed before the successful selection run.

## Interpretation boundary

The curation contrast now estimates a static metadata-rarity selector versus stratified random sampling from one fixed universe. It does not estimate the value of iterative greedy coverage. No selected IDs, model outcomes, model embeddings, or evaluation labels were inspected before the amendment.

