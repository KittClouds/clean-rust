# Frizz Phase 5 — BANK-v3-core access lane

Completed synthetic-only bridge and bounded access ladder; protected evaluation unopened.

## Fixed endpoints

| Arm | Goal BA | Legal BA | Exact logged action | Optimal-set hit | Disposition |
|---|---:|---:|---:|---:|---|
| bridge | 0.7479 | 0.8042 | 30/333 | 30/333 | FROZEN_REFERENCE |
| E | 0.8089 | 0.8039 | 32/333 | 32/333 | SURVIVES_AS_CONSTRUCTED |

Exact logged candidate and optimal membership are separate endpoints even when their values coincide. Empty optimal sets are excluded (2,667 bridge DEV roots). Only MOVE has enough DEV action-class support (249). Other action classes remain descriptive; TRANSFER has zero DEV endpoint support.

## Acquisition versus initial accessibility

| Arm | Production goal init → trained | Fixed e-linear goal init → trained |
|---|---:|---:|
| bridge | 0.5874 → 0.7479 | 0.6750 → 0.7487 |
| E | 0.5874 → 0.8089 | 0.6750 → 0.8134 |

All declared linear/MLP arms are retained, not a post-hoc best readout. Candidate-local, candidate+context and integrated-state recovery remain separate. E/F begin at the untrained bridge initialization with exact zero-residual equivalence.

## Frozen response-vector decisions

### E: SURVIVES_AS_CONSTRUCTED

Logical gates: {"fixed_linear_access": true, "no_hard_loss_regression": true, "preservation_vector": true, "primary_cells": true}.

- binding: 781 roots; positive/negative roots 209/781; relative balanced-loss reduction +24.975%; paired loss-improvement CI [0.06787044921643003, 0.1750916871566602]; improved=True.
- candidate_comparison: 1262 roots; positive/negative roots 320/1262; relative balanced-loss reduction +4.700%; paired loss-improvement CI [-0.04344578409964699, 0.1207236514843774]; improved=False.
- globalization: 965 roots; positive/negative roots 250/965; relative balanced-loss reduction +39.471%; paired loss-improvement CI [0.17932112110820994, 0.2536337068238838]; improved=True.

Preservation failures: none.

Fixed e-linear goal gain: {"delta": 0.06468494899525934, "ci95": [0.050089842093870574, 0.07988030147959163], "bootstrap_roots": 3000, "repetitions": 2000, "seed": 20261002, "positive_roots": 702, "negative_roots": 3000}.

Proper-loss slice improvement is not a positive-class recoverability claim when positive root support is underpowered. Retirement is of this construction and dose, not the substrate or entire family. No automatic widening/deepening.

## Costs and replay

Extraction: 30,000 full-text rows in 3188.8768700000073 seconds; max 1,415 tokens. Six qualified surfaces; 752,393,024 frozen BF16 text parameters.

| Arm | Trainable parameters | Fixed buffer elements | Training seconds | Peak CUDA bytes | Cached graft seconds/root |
|---|---:|---:|---:|---:|---:|
| bridge | 2174344 | 0 | 245.84 | 1933853696 | 0.000210 |
| E | 2344052 | 0 | 270.27 | 2050684928 | 0.000344 |

Latency excludes frozen Qwen extraction and is local cached-feature throughput, not a serving benchmark. Fresh-process exact production/axis/ablation replay and persisted-probe prediction replay pass. This is replay using frozen authored code, not an independently authored semantic oracle.

## Scientific and engineering scope

Baseline: action type + deterministic positional argument vectors + global/context. E adds typed relational integration, not the first trace of schema. No recurrence, stochasticity, LoRA or IHA. No v1-to-v3 mechanism claim, no composite score.

All ten axes, hard slices, restricted-target strata, renderer supports and endpoint denominators are in each run/receipt.json and recorder-v01/axis-readouts.json. Conflict remains diagnostic-only with zero loss. Global goal-satisfied positive support is only 167 DEV roots, so its positive-class reliability claim is underpowered.

Preserved repairs: Windows separator packaging defect; missing-Path preparation failure; unbound observable action arguments before assembly. Unbound slots use zero entity vectors without dropping candidates or guessing from truth (2,664 TRAIN and 664 DEV renderings).

Ablation names require care: zero_context zeros cached global surfaces, not the contextual information already inside entity vectors; zero_action_types substitutes index 0 (MOVE), not a zero embedding; zero_entities zeros candidate argument vectors while explicit E/F goal pools remain available. These descriptive interventions are not proofs of complete context/type/entity removal.

No protected evaluation files opened; this is DEV phenotype and acquisition evidence, not protected generalization. Lexi and Phase 6 remain untouched.
