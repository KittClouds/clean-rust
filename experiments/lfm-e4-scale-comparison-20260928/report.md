# E4 230M versus 1.2B paired capability comparison

Both frozen Base backbones used identical E1 FIT-derived TRAIN/DEV identities and the same
independent 74,668-row E4-shaped TEST. Five linear observers were refit for each model.
The protected E4-0 panel was not used. This is a synthetic capability comparison,
not a lexical-transport or serving qualification.

TEST population seal: `f9a368c85766f8b24e43c2fb9bcd90a03e0acf9bd0acfd10035783da73e3ebba`.
230M TEST prediction seal: `f9cb0b19b5a86349a78bc8640fd558f69819e36317b83555276a6029d5459359`.
1.2B TEST prediction seal: `d8af8ffa28004e5f35632653c1f4bc4510ffab0b299428a02115e45a5f5cb2ec`.

| Endpoint | 230M balanced | 1.2B balanced | 230M E4 0.625th percentile | 1.2B E4 0.625th percentile | 1.2B minus 230M paired 90% interval |
|---|---:|---:|---:|---:|---:|
| `context_identity` | 99.837% | 99.837% | 99.795% | 99.795% | [-0.038%, 0.037%] |
| `entity_identity` | 99.893% | 99.897% | 99.858% | 99.864% | [-0.025%, 0.033%] |
| `relation` | 100.000% | 100.000% | 100.000% | 100.000% | [0.000%, 0.000%] |
| `observed_state` | 99.967% | 99.996% | 99.935% | 99.984% | [0.008%, 0.049%] |
| `exact_target_in_domain` | 99.959% | 99.992% | 99.923% | 99.971% | [0.012%, 0.057%] |
| `exact_target_context_novel` | 99.242% | 99.864% | 99.062% | 99.796% | [0.503%, 0.743%] |
| `exact_target_entity_novel` | 98.666% | 99.861% | 98.414% | 99.795% | [1.032%, 1.362%] |
| `exact_target_both_novel` | 98.297% | 99.425% | 96.762% | 98.755% | [0.217%, 2.136%] |

E4-shaped eight-endpoint floor diagnostic (0.90, Bonferroni 0.00625): 230M **PASS**, 1.2B **PASS**. This comparison does not score or qualify the protected E4-0 panel.

| Integrated on in-domain rows | 230M | 1.2B |
|---|---:|---:|
| All four route heads correct | 99.719% | 99.719% |
| Route and exact target correct | 99.679% | 99.711% |

| Cost diagnostic | 230M | 1.2B |
|---|---:|---:|
| Hidden dimension | 1024 | 2048 |
| Frozen model bytes | 459,401,112 | 2,340,697,936 |
| Five-head trainable parameters | 73,800 | 147,528 |
| Five-head fit time (s) | 24.65 | 60.93 |
| TEST feature bytes | 305,840,128 | 611,680,256 |
| TEST extraction loop time (s) | 2774.82 | 3135.86 |
| TEST extraction loop ms/row | 37.16 | 42.00 |

The extraction runs may overlap on one GPU, so loop timings are workload diagnostics rather than
a clean isolated latency benchmark. The linear heads force a prediction and have zero abstentions.
Inference cost here includes the frozen backbone, not a serving-optimized batch path.
