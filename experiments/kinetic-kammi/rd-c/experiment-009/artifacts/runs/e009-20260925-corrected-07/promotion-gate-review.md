# E009 promotion gate review

Run: `e009-20260925-corrected-07`. Thresholds were frozen from development at **850 applicability milli / 150 abstention milli**.

## Result

The hybrid completed **8/8**, matching always-large. It made **5 large calls versus 8** and used **38.28s versus 49.04s** in the serial local harness, a **21.9%** reduction in summed task time. The small observer acted directly on 3 of 8 tasks; all three selected actions passed. It abstained on five tasks, which the large model recovered.

Token use increased: **13,859 versus 9,302**, up **4,557 tokens (49.0%)**. The hybrid passes the declared gate on completion, fewer large calls, and measured time, but not on token cost. Local inference was unbilled; energy and hardware-dollar cost were not measured.

Task p50 was 3.45s versus 3.87s. p95 was 14.31s versus 14.05s, so the tail did not improve on this eight-task sample. Times sum per-task model and authority timings; pre-contact completion-test builds are excluded because the scorer reused exact hash-verified receipts.

Authority checks reported **zero illegal commits, zero rejected transitions, zero duplicate action effects, and identical replayed state**. The hand-written lane completed 4/8 with one wrong legal action. The small-only lane completed 3/8, made no wrong legal actions, and abstained five times.

## Scope

The bank contains four fresh task families, two prompts per family, from one frozen repository commit. The family is the variation unit. This supports a task-family fast lane in this repository; it does not establish cross-repository transfer.

A score-only attempt opened held-out labels and stopped before lane results because of a receipt-reader schema mismatch. The corrected replay used the same frozen observer outputs, thresholds, bank, and test receipts. No held-out labels were used for fitting or prompt changes. The access history is recorded in the run status and score replay lock.

## Decision

**E009 passes its limited compute-router gate for measured time and large-call reduction.** Keep the v5 small-observer action region as an engineering candidate with large fallback, and keep the token increase visible. E010 should test the same frozen switchboard on independently selected task families from a different repository before widening the claim.
