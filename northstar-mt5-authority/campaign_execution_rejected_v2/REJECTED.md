# Pre-admission execution rejection

This frozen sampling frame selected the correct weeks but used Friday 23:55 as
the deterministic cutoff. It was never admitted into the corpus.

Status: `REJECTED_PRE_ADMISSION`

During the Phase 7 pilot, the FRA40 event-heavy week ended on Thursday because
Friday was a market holiday. No calculation bar could reach the frozen Friday
cutoff, so MT5 force-closed the test with a START-only run receipt.

Replacement: `RG2_SIX_INDEX_ENVIRONMENT_FRAME_V3`. It preserves every selected
week and sampling reason while binding each cutoff to the final observed M5 bar
inside that instrument-window.
