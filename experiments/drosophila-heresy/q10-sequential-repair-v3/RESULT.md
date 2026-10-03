# Q10-SR3 result

Status: `Q10_SR3_STAGE2A_INVALID`

SR3 Stage 1A passed independent committed-byte review: seed `9521` produced
1,024 verified engineering events, with 1,002 capacity-gated events and zero
search entries or repairs.

Stage 1B opened seeds `9522..9525`. Two blocks completed for seed `9522`
(`R/tau4` and `R/tau16`), producing 512 event receipts. The next block,
`L/tau4`, entered a single deterministic capacity-factorization worker and did
not commit within the declared 10-minute block window. Eight workers were
waiting while one worker remained active; memory stabilized near 267 MB. The
run was stopped through its terminal session before any partial block could be
written.

This is an engineering performance abort of the frozen factorization policy,
not a repair, capacity, impossibility, behavioral, or scientific result. The
two completed Stage 1B bundles and the verified Stage 1A directory are
preserved. Seeds `9523..9525` remain unopened, and SR3 may not be resumed or
tuned under the same identity. Any continuation needs a new protocol identity
with a bounded factorization or precomputed/reused capacity design.
