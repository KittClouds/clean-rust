# Q10-BG Stage 1 result

Status: `Q10_STAGE1_VALID__BOUNDED_FREEDOM_PRESENT`

Q10 Stage 1 completed as a qualification-only engineering audit. It used zero
scientific seed bundles and performed no behavioral inference. Q08 and Q09
were not mutated.

## Receipts

- Stage 1A: engineering seed `9301`, 1,024 new states.
- Stage 1B: engineering seeds `9302..9305`, 4,096 new states.
- Cumulative Stage 1 states: 5,120.
- Both stages independently verified by NumPy replay.
- All completed events passed continuous support, boundary, box, linear-drive,
  acquisition-axis, norm, and null-annihilation checks.

## Bounded geometry

Across all 5,120 states:

- Bounded non-identity endpoints: 5,006.
- Box-constraint-dominated events: 114.
- Residual cosine `c_box`: `0.9991022301..0.9999999999995`; median
  `0.9999921165`.
- Path-safe rotation angle: `1.019e-6..0.04238` radians; median
  `0.003971` radians.
- Minimum alternate interior slack: `8.61e-16..1.59e-11`; median
  `2.45e-12`.
- Combined rank: `663..696`; median `680`.
- Combined nullity: `4,878..9,515`; median `7,735`.

The box leaves a valid but very narrow continuous residual wedge. The reported
rotation is the frozen path-safe constructor's result, not a claim that the
global endpoint optimum has been solved.

## Integrity maxima

The largest observed absolute errors were `8.88e-16` for cue-by-MBON drive
equality, `9.60e-15` for acquisition-axis displacement, `1.76e-14` for null
annihilation, and `5.20e-14` for total norm preservation. The independent
replay verified these constraints again.

## Stage 2 decision

Stage 2 was not entered. The continuous endpoints are deliberately selected
near the box limit, with median slack `2.45e-12`, far below the f32 spacing at
these weight magnitudes. Committing those endpoints would confound the
committed-f32 repair question with immediate boundary quantization.

The next Q10 identity should add a frozen f32 safety-margin rule to the
continuous constructor, then qualify committed readout and local ULP repair
against that margin. No DH-08B authorization follows from Q10.
