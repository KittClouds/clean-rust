# Q10-DN1 result

Status: `Q10_DN1_INVALID`

DN1 was sealed successfully but failed during the first diagnostic execution
before committing any bundle. The implementation attempted to eigendecompose
an empty per-coordinate Gram matrix and also contained a local-versus-global
row-index error in the local Gram update. No scientific bundle, behavioral
output, or diagnostic event receipt was committed.

The identity is closed and may not be patched or resumed. DN2 carries the
predeclared sample and corrected implementation under a fresh seal.
