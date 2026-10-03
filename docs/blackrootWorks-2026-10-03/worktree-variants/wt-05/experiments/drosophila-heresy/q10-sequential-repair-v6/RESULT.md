# Q10-SR6 result

Status: `Q10_SR6_STAGE2A_INVALID`

Q10-SR6 attempted to audit the frozen search's 16-step-per-coordinate effect
vocabulary without materializing the large SR5 bank. It streamed each legal
multi-step sparse effect directly into a 784-row f64 Gram matrix and retained
only the matrix and readout vectors.

The representation improved the SR5 memory behavior but did not make the full
qualification tractable. Stage 1A seed `9551` was opened, but after a bounded
10.18-minute observation window it had committed only the pre-execution receipt
and no bundle. The observed working set peaked near 1.37 GB; the producer was
stopped cleanly and Stage 1B seeds `9552..9555` were never opened.

This is a performance qualification failure, not a capacity, repair,
impossibility, behavioral, or scientific result. Q10-SR6 may not be resumed or
tuned under the same identity. The combined SR5/SR6 evidence rules out a naive
full multi-step capacity audit over every state. The next useful step is a
small, explicitly diagnostic event sample or an analytic row-authority audit,
not another full-seed qualification with the same 16-step replay loop.
