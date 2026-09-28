# E004 Frozen Run Escalation Audit

Run: `e004-1790275031951709800`. This is a diagnostic audit of the existing 2,048-row run trace; it does not alter or rescore the frozen run.

## Outcome definition

Each routed episode compares the active observer action with the resolver action against the hidden correct action. The four categories are wrong→right, right→wrong, both right, and both wrong. `Net correct conversions` is wrong→right minus right→wrong.

Confidence bands are `<700`, `700–899`, and `>=900`. `Witness` uses the frozen trace label. The CSV summary breaks every category out by policy and budget, then by witness, observer disagreement, and confidence band.

## Budget 16: combined versus matched random

Combined routed outcomes: {'both_wrong': 16}; net correct conversions `0`. Matched random: {'both_right': 11, 'both_wrong': 2, 'wrong_to_right': 3}; net correct conversions `3`.
Combined ended at 80/128 completions versus random at 83/128. The difference in route conversion yield is -3; all other episodes retain their active action. Use the per-episode file for the exact cases and witness/disagreement/confidence slices.

## Combined budget 32 to 48 plateau

The 32-call selection is nested in the 48-call selection: `True`. The 16 newly routed episodes have outcomes {'both_right': 16} and net correct conversions `0`. Completion stayed at 96/128 because the marginal resolver calls produced no net correct-action changes.

## Journal-byte unit correction

`journal_bytes` in the trace is a byte count for the complete E002 task journal (8-byte RDC2 header plus newline-delimited journal envelopes), not KiB. The sampled trace field matches the on-disk `task.journal` length exactly; across routed rows, mean file size was 13,081.5 bytes and mismatches were 0/640.

The E004 report formatted `mean(journal_bytes) / episode_count`, dividing by the task count twice. Its displayed 97.7–101.1 is therefore approximately bytes-per-task divided by 128, not journal bytes per task. Correct E004 values are about 12.5–12.9 KB per task, consistent in scale with E003’s 12–13 KB. The frozen report is left unchanged; this audit records the correction.

## Limits

The counts describe this synthetic frozen bank and deterministic resolver. The audit explains where the observed completion changes came from; it does not establish that these routing signals predict useful inspection on a different workload.
