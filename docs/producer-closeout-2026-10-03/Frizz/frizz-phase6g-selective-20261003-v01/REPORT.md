# Phase 6G — selective legality under observable uncertainty

SELECTIVE_CLASSIFIER_RETIRED_FALSE_CERTAINTY

Frozen Qwen/E caches; one 365→128→64→3 classifier, twelve fixed epochs. No new extraction, backbone training, LoRA, bank changes or protected evaluation contact.
Targets are the sealed strict observable statuses, not canonical binary legality. Unknown candidates have no canonical legality loss.

| Primary renderer | Macro F1 | BA | False certainty (true U) | Certainty coverage | Exact three-way roots |
|---|---:|---:|---:|---:|---:|
| D binary | 0.3342 | 0.5268 | 100.00% | 100.00% | 0.00% |
| Selective init | 0.1144 | 0.3476 | 28.04% | 42.79% | 0.00% |
| Selective epoch12 | 0.5159 | 0.6946 | 45.94% | 78.29% | 0.30% |

## Frozen rule and interpretation

Survival requires false certainty ≤5%, certainty coverage ≥70%, and ≥5 percentage-point exact observable partition gain over the prospectively fixed D-trained binary baseline. No best raw baseline or threshold was selected. Primary rendering is fixed; paired rendering, init delta and every binary baseline remain reported.
{
  "automatic_escalation": false,
  "certainty_coverage": 0.7828659415245056,
  "disposition": "SELECTIVE_CLASSIFIER_RETIRED_FALSE_CERTAINTY",
  "exact_partition_delta_vs_D_trained": 0.0030030030757188797,
  "false_certainty": 0.4593899301727306,
  "material_improvement_threshold": 0.05,
  "no_canonical_information_ceiling_claim": true,
  "primary_renderer_fixed": true,
  "survives": false
}

False certainty is conditional on true UNRESOLVED candidates; false abstention is conditional on true CERTAIN candidates. Absolute all-candidate fractions and all supports are also recorded. This task is not canonical exact legal-set recovery.
The strict deterministic oracle is the status reference: its candidate certainty coverage is bounded by unresolved observable evidence. It does not promise the frozen ranker can choose the logged or optimal candidate. Oracle filtering removes only CERTAIN_ILLEGAL and retains all UNRESOLVED candidates.

## Class responses

| Class | Support | Precision | Recall |
|---|---:|---:|---:|
| CERTAIN_ILLEGAL | 17596 | 0.9159365874009178 | 0.7486360536485565 |
| CERTAIN_LEGAL | 472 | 0.19809825673534073 | 0.7944915254237288 |
| UNRESOLVED | 2721 | 0.3258750553832521 | 0.5406100698272693 |

False abstention: 16.84%; exact certain-legal set: 35.14%; exact certain-illegal set: 0.30%.

## Selection and procedural authorization

All ranking uses unchanged Phase6C cost and stable candidate-index ties. UNKNOWN is never pruned. Full-set and gold-type-conditioned exact logged ranking and optimal-set ranking have separate denominators. Uncertainty slices are fixed from the true strict observable partition; predicted slices are separately descriptive.
Authorization uses the model-chosen winner, not the gold logged candidate. It requires predicted CERTAIN_LEGAL and resolved rivals with frozen cost no worse than the winner, including ties. This is procedural authority under the frozen ranking contract, not policy permission, optimality certification or canonical truth assurance.

### model

Full selected top1/MRR: 0.0030030030757188797 / 0.1486392617225647 (n=333); same-type top1/MRR: 0.12012012302875519 / 0.2633386552333832 (n=333).
Authorized full-menu roots: 333/333; coverage 100.00%; logged accuracy among authorized eligible roots 0.003003003003003003; optimal hit 0.003003003003003003; oracle-status-consistent fraction 1.0.

### no_filter

Full selected top1/MRR: 0.0030030030757188797 / 0.1845308542251587 (n=333); same-type top1/MRR: 0.13813814520835876 / 0.34679022431373596 (n=333).

### observable_oracle

Full selected top1/MRR: 0.0030030030757188797 / 0.3558342754840851 (n=333); same-type top1/MRR: 0.6126126050949097 / 0.7553818821907043 (n=333).
Authorized full-menu roots: 333/333; coverage 100.00%; logged accuracy among authorized eligible roots 0.003003003003003003; optimal hit 0.003003003003003003; oracle-status-consistent fraction 1.0.

## Verification and preservation

Trainable parameters: 55299; fixed training time: 22.19s. Detailed forward latency/checkpoint size in evaluation-cost.json. Root-normalized TRAIN CE and TRAIN-only balancing/normalization are pinned in TRAIN-contract.json and normalization.pt.
Unit controls cover perfect three-way recovery, binary false-certainty, root-balanced loss, unresolved retention, tied-unknown authorization veto and exact candidate permutation equivariance. Independent reconstruction checks all strict labels against actual sealed TRAIN/DEV worlds. Fresh-process replay reproduces init/epoch12 logits, every metric, all binary rescoring and disposition exactly.
Qwen, E, goal heads and frozen ranker remain unmodified and their identities are hash-checked. This experiment learns observable statuses only; canonical truth is confined to diagnostic truth correctness. No protected evaluation files opened.
All renderer/candidate-count slices, root arrays, class denominators, selected/optimal endpoints and authority denominators are in the machine-readable package. No composite score, automatic escalation or rescue fit.
