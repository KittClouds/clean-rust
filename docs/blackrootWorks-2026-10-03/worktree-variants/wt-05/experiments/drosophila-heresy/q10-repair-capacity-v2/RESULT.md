# Q10-RC2 result

Status: `Q10_RC_INVALID`

The corrected retained-right-subspace QR implementation completed the full seed `9611`, side `R`, tau `4` block, demonstrating that Q10-RC v1's reconstruction failure came from the returned SVD left vectors rather than the frozen rank decision. During the next block, the move-bank SVD failed to converge under the frozen `1e-14` tolerance and `100000` iteration budget.

Stage A therefore remains invalid despite 256 partial engineering receipts. No scientific seed, behavior, repair, or multi-move evaluation was used. Switching to a Gram or different factorization after this observation would require another protocol identity and fresh seeds; Q10-RC2 does not authorize that continuation.
