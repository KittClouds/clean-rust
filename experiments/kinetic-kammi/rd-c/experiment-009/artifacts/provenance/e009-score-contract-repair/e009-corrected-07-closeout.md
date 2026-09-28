# E009 corrected-07 closeout

## Engineering repairs

The earlier scorer could credit a test-passing patch after E002 rejected its execution proposal. The corrected evaluator requires both an authorized action receipt and a passing patch completion receipt. The hand-written lane now consumes task evidence, and the scorer uses the normalized v2 observer scores. The earlier v5 heldout bank was already exposed, so corrected-03/04 remain diagnostics.

A new v6 family-heldout bank was built from four distinct existing test families. Each keep/gold/gold-comment/mutant candidate was run against the exact frozen test before model contact; all tests separated the intended repairs from the injected faults. The v5 development thresholds remained fixed at 850/150. The v5 small and large bundles then observed all eight v6 frames with successful typed output collection.

The score-only evaluator now reuses exact test results from the pre-contact bank build. It verifies candidate patch identity, test-log hashes (canonicalized to LF), the build receipt, and the complete bank tree. This avoids repeating Cargo linking across lanes. Task time excludes the one-time completion-test build and is reported as summed per-task observer and authority time.

## Scoring repair trace

`corrected-06` opened heldout labels, then stopped before writing any lane rows: its reader expected `test_filter` under each variant, while the receipt stores it at family level. During repair, an audit caught CRLF files being compared against LF-canonical receipt hashes. The verifier now normalizes line endings before hashing, and future bank logs are written with LF. `corrected-07` replayed the same frozen model outputs, labels, thresholds, task bank, and completion receipts. No threshold, prompt, model, or bank change followed label access. Both attempts and this history remain recorded.

## Result

The hybrid completed 8/8, matching always-large; it made 5 rather than 8 large calls. Summed task time was 38.28s versus 49.04s (**21.9% lower**). Token use was 13,859 versus 9,302 (**49.0% higher**). There were zero illegal commits, zero rejected transitions, zero duplicate action effects, and replayed state matched exactly.

The measured-time and large-call gate passes for these four task families. Token cost rises; actual energy and hardware-dollar cost are unknown. E010 should use independent families from another repository before widening the result.

## Frozen artifact hashes

See `e009-corrected-07-closeout.json` for hashes of the split, frames, labels, candidate lock, test receipts, observer lock/output trees, score replay lock, report, and current evaluator/builder. The v6 bank-build receipt did not capture source-builder hashes; the shared builder now includes those hashes in future receipts.
