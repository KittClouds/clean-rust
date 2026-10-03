# Q08 independent smoke review

Status: `SMOKE_CONSTRUCTOR_FAILED`. Integrity: `VALIDATED`.

All 512 event receipts were retained. 512 events failed the pre-smoke contract. R failed
256 / 256; L failed 256 / 256.

503 events have an optimistic grouping-constrained
decorrelation floor above the frozen gate under the quadruple implementation;
482 retain a positive floor above the gate even allowing
all signature-group nullspaces. This is a constructor-contract limitation, not a theorem
about all possible nonlinear readout-preserving endpoints. Full qualification and DH-08B measured
execution remain gated if any event failed. No task performance was analyzed and no scientific seed
bundle was opened.
