# F4-SYMMETRY-01 Results

**Disposition:** qualification-only representation diagnosis. No measured REACH-03 result, biological promotion, native-rule change, or PHENO change follows from this run.

## HIST provenance

HIST is a legacy qualification provenance anchor. Its 80D values, including expected-score fields, were excluded from A/B/C/D and it was not fitted here.

## A: clean admissible baseline

Pooled out-of-fold IPW-balanced error = 0.665272226; clipped Omega-hat = 0.

## B-A: descriptive width/control contrast

error_B - error_A = 0.0742672144. B is a deterministic 24D transform of fold-normalized A.

## C-B: primary relational-sidecar contrast

error_C - error_B = -0.0996064873. Negative values favor lower held-out error for the declared relational-sidecar package.

## D-C: primary canonical-ordering contrast

error_D - error_C = -0.100724688. Negative values favor lower held-out error when those same tuple values are canonically ordered.

## Blockwise signed margins

- A, block 303000: balanced error=0.8123775567825526; signed margin=-2.10861818 (class_balanced_q_weighted).
- A, block 303001: balanced error=0.49977947336958867; signed margin=-3.31382772 (class_balanced_q_weighted).
- A, block 303002: balanced error=0.5644077335113149; signed margin=-3.0731583 (class_balanced_q_weighted).
- A, block 303003: balanced error=None; signed margin=4.23547759 (one_class_q_weighted_Y_times_logit).
- B, block 303000: balanced error=0.7801158423416065; signed margin=-1.59216665 (class_balanced_q_weighted).
- B, block 303001: balanced error=0.5030372663786906; signed margin=-3.26036119 (class_balanced_q_weighted).
- B, block 303002: balanced error=0.6612548065320245; signed margin=-3.81985864 (class_balanced_q_weighted).
- B, block 303003: balanced error=None; signed margin=-5.62610292 (one_class_q_weighted_Y_times_logit).
- C, block 303000: balanced error=0.7604550884922758; signed margin=-2.06067004 (class_balanced_q_weighted).
- C, block 303001: balanced error=0.5251735372704571; signed margin=-4.52685535 (class_balanced_q_weighted).
- C, block 303002: balanced error=0.5076816752965081; signed margin=-2.70066531 (class_balanced_q_weighted).
- C, block 303003: balanced error=None; signed margin=2.22330007 (one_class_q_weighted_Y_times_logit).
- D, block 303000: balanced error=0.2044483909599551; signed margin=1.40196363 (class_balanced_q_weighted).
- D, block 303001: balanced error=0.47944849115504684; signed margin=0.317627729 (class_balanced_q_weighted).
- D, block 303002: balanced error=0.529145722374589; signed margin=0.0462662039 (class_balanced_q_weighted).
- D, block 303003: balanced error=None; signed margin=3.05695409 (one_class_q_weighted_Y_times_logit).

## Secondary polarity and delivery metrics

- A: Psi=0.08185118644879297; delivered cosine=0.0014516264914928392.
- B: Psi=0.07208985980713822; delivered cosine=0.012644252215697201.
- C: Psi=0.049689886650434056; delivered cosine=-0.005831090492769506.
- D: Psi=0.4469275412111533; delivered cosine=0.0827759962727222.
- Native proposed sign: Psi=-0.13193289961694998.
- Oracle reference sign: Psi=1.0.

The first-order Psi and delivery cosine are local sidecars. They do not guarantee endpoint capability under bounded multi-step dynamics.
