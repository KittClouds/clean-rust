# Q10-ALG4-COMP1 preflight plan

This identity seals an order-4 composition preflight for context `seed9731-R-tau4.json`, set 3. It is engineering-only: scientific promotion is false and no long measurement is started in this phase.

The A3 anchor manifest is derived only from the R2-v3 `results/order1_hits.jsonl` receipt. It contains anchor ordinals 360 and 362 and target rows 161, 357, and 749. Each candidate is one distinguished anchor plus three singleton compensators from three distinct groups. Group 45 is the anchor group, so its 58 other groups provide the compensator pool. Coordinate disjointness is verified from the frozen EXH1 context. COMP1A additionally excludes compensator footprints intersecting the A3 rows; COMP1B keeps the same compatible pool without that footprint exclusion. In this frozen domain the exclusion removes no eligible action because all excluded actions are in group 45, which is already unavailable.

The canonical domain stream is independent of class label: for each anchor in ordinal order (360 then 362), each lexicographic triple of compensator groups, and each action combination in group order, hash a little-endian `<u16 anchor, u16 action_a, u16 action_b, u16 action_c>` record. The stream is not replay output and contains no candidate scores or witness bodies. Both class manifests bind the same count and stream hash while retaining separate policy labels.

Only static/domain enumeration and hash sealing are authorized now. `run_alg4_comp1.py --preflight` refuses all other invocations. A later measurement, if separately authorized, must use this sealed identity and the shared domain stream; it must not mutate any parent identity.
