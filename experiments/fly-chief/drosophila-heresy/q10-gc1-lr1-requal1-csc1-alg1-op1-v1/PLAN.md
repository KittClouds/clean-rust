# Q10-CSC1-ALG1-OP1: derived f32 composition-order audit

This read-only identity consumes the sealed UPAIR1 pair receipts and tests
alternative parenthesizations of additive f32 readout composition. It performs
no pair replay. The original ALG1 operator `f32(f32(A+B)-S)` is retained as a
baseline. Additional fixed operators use the same A, B, and S readout bits
with different subtraction/addition order:

* `A + (B - S)`;
* `(A - S) + B`;
* `S + (A - S) + (B - S)` left-associated;
* `S + ((A - S) + (B - S))`.

Every operator is evaluated with explicit f32 rounding after each binary
operation. Results are compared bitwise with the already-replayed AB readout.
This is a retrospective arithmetic diagnostic only. It does not alter ROUTE1,
open a new pair domain, or promote the compositional-algebra hypothesis.
