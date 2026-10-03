# Phase 11 — Empirical Structure Report

Status: **PASS**  
Corpus: `9cbad8545db23cba7ccea2bd062aeba700597deb4be19cecbb74647f65ef8413`  
Reserved holdout windows touched: **0**

This report describes market-behavior targets only. It contains no trade labels, expectancy,
position sizing, or holdout evaluation. Attempts are resampled and validated by run; they are
never treated as independently shuffled rows.

## Target geometry

| target | eligible | analyzable | positive | negative | censored | rate | censoring_rate | runs | episodes | median_time_seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| reclaim_given_break | 2073 | 1547 | 880 | 667 | 526 | 0.5688 | 0.2537 | 20 | 551 | 600.0000 |
| initial_acceptance_given_initial_contact | 5737 | 5051 | 667 | 4384 | 686 | 0.1321 | 0.1196 | 20 | 897 | 390.0000 |
| rejection_given_initial_contact | 5737 | 5051 | 3504 | 1547 | 686 | 0.6937 | 0.1196 | 20 | 897 | 390.0000 |
| retest_hold_given_retest_contact | 1267 | 1251 | 763 | 488 | 16 | 0.6099 | 0.0126 | 20 | 329 | 266.0000 |
| transit_given_episode_acceptance | 386 | 263 | 227 | 36 | 123 | 0.8631 | 0.3187 | 19 | 263 | 0.0000 |

## Dependence and effective sample size

| target | cluster_unit | rows | clusters | mean_cluster_size | icc | design_effect | effective_n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| reclaim_given_break | run_key | 1547 | 20 | 77.3500 | 0.0027 | 1.2077 | 1280.9785 |
| reclaim_given_break | episode_id | 1547 | 551 | 2.8076 | 0.0374 | 1.0677 | 1448.9340 |
| initial_acceptance_given_initial_contact | run_key | 5051 | 20 | 252.5500 | 0.0119 | 4.0041 | 1261.4504 |
| initial_acceptance_given_initial_contact | episode_id | 5051 | 897 | 5.6310 | 0.2129 | 1.9857 | 2543.6650 |
| rejection_given_initial_contact | run_key | 5051 | 20 | 252.5500 | 0.0371 | 10.3352 | 488.7162 |
| rejection_given_initial_contact | episode_id | 5051 | 897 | 5.6310 | 0.5515 | 3.5541 | 1421.1903 |
| retest_hold_given_retest_contact | run_key | 1251 | 20 | 62.5500 | 0.1021 | 7.2817 | 171.8012 |
| retest_hold_given_retest_contact | episode_id | 1251 | 329 | 3.8024 | 0.5206 | 2.4590 | 508.7332 |
| transit_given_episode_acceptance | run_key | 263 | 19 | 13.8421 | 0.0439 | 1.5631 | 168.2522 |
| transit_given_episode_acceptance | episode_id | 263 | 263 | 1.0000 |  |  | 263.0000 |

## Hard baselines

| target | split_type | model | rows | prevalence | log_loss | brier | auc | average_precision | ece_10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| reclaim_given_break | FORWARD_TIME | NULL_PREVALENCE | 827 | 0.5586 | 0.6870 | 0.2469 | 0.4857 | 0.5535 | 0.0420 |
| reclaim_given_break | FORWARD_TIME | RIDGE_LOGISTIC | 827 | 0.5586 | 0.6655 | 0.2368 | 0.5890 | 0.6045 | 0.0583 |
| reclaim_given_break | GROUPED_RUN | NULL_PREVALENCE | 1547 | 0.5688 | 0.6844 | 0.2457 | 0.4718 | 0.5559 | 0.0279 |
| reclaim_given_break | GROUPED_RUN | RIDGE_LOGISTIC | 1547 | 0.5688 | 0.6555 | 0.2317 | 0.6089 | 0.6422 | 0.0311 |
| reclaim_given_break | INSTRUMENT_TRANSFER | NULL_PREVALENCE | 1547 | 0.5688 | 0.6846 | 0.2457 | 0.4628 | 0.5464 | 0.0484 |
| reclaim_given_break | INSTRUMENT_TRANSFER | RIDGE_LOGISTIC | 1547 | 0.5688 | 0.6648 | 0.2360 | 0.5872 | 0.6363 | 0.0330 |
| initial_acceptance_given_initial_contact | FORWARD_TIME | NULL_PREVALENCE | 2840 | 0.1285 | 0.3839 | 0.1121 | 0.4836 | 0.1170 | 0.0281 |
| initial_acceptance_given_initial_contact | FORWARD_TIME | RIDGE_LOGISTIC | 2840 | 0.1285 | 0.3279 | 0.1002 | 0.7904 | 0.2973 | 0.0381 |
| initial_acceptance_given_initial_contact | GROUPED_RUN | NULL_PREVALENCE | 5051 | 0.1321 | 0.3907 | 0.1147 | 0.4721 | 0.1234 | 0.0186 |
| initial_acceptance_given_initial_contact | GROUPED_RUN | RIDGE_LOGISTIC | 5051 | 0.1321 | 0.3350 | 0.1031 | 0.7769 | 0.2923 | 0.0195 |
| initial_acceptance_given_initial_contact | INSTRUMENT_TRANSFER | NULL_PREVALENCE | 5051 | 0.1321 | 0.3905 | 0.1147 | 0.4719 | 0.1215 | 0.0294 |
| initial_acceptance_given_initial_contact | INSTRUMENT_TRANSFER | RIDGE_LOGISTIC | 5051 | 0.1321 | 0.3277 | 0.1007 | 0.7872 | 0.3125 | 0.0133 |
| rejection_given_initial_contact | FORWARD_TIME | NULL_PREVALENCE | 2840 | 0.7088 | 0.6050 | 0.2072 | 0.5063 | 0.7112 | 0.0530 |
| rejection_given_initial_contact | FORWARD_TIME | RIDGE_LOGISTIC | 2840 | 0.7088 | 0.3483 | 0.1101 | 0.9073 | 0.9605 | 0.0349 |
| rejection_given_initial_contact | GROUPED_RUN | NULL_PREVALENCE | 5051 | 0.6937 | 0.6176 | 0.2131 | 0.4568 | 0.6633 | 0.0474 |
| rejection_given_initial_contact | GROUPED_RUN | RIDGE_LOGISTIC | 5051 | 0.6937 | 0.3735 | 0.1174 | 0.8952 | 0.9511 | 0.0385 |
| rejection_given_initial_contact | INSTRUMENT_TRANSFER | NULL_PREVALENCE | 5051 | 0.6937 | 0.6173 | 0.2130 | 0.4539 | 0.6668 | 0.0395 |
| rejection_given_initial_contact | INSTRUMENT_TRANSFER | RIDGE_LOGISTIC | 5051 | 0.6937 | 0.3611 | 0.1124 | 0.9006 | 0.9531 | 0.0290 |
| retest_hold_given_retest_contact | FORWARD_TIME | NULL_PREVALENCE | 664 | 0.6175 | 0.6664 | 0.2367 | 0.4640 | 0.6115 | 0.0835 |
| retest_hold_given_retest_contact | FORWARD_TIME | RIDGE_LOGISTIC | 664 | 0.6175 | 0.4307 | 0.1355 | 0.8772 | 0.9089 | 0.0621 |
| retest_hold_given_retest_contact | GROUPED_RUN | NULL_PREVALENCE | 1251 | 0.6099 | 0.6771 | 0.2418 | 0.4051 | 0.5615 | 0.1192 |
| retest_hold_given_retest_contact | GROUPED_RUN | RIDGE_LOGISTIC | 1251 | 0.6099 | 0.4574 | 0.1449 | 0.8679 | 0.8982 | 0.0727 |
| retest_hold_given_retest_contact | INSTRUMENT_TRANSFER | NULL_PREVALENCE | 1251 | 0.6099 | 0.6772 | 0.2419 | 0.4120 | 0.5386 | 0.1011 |
| retest_hold_given_retest_contact | INSTRUMENT_TRANSFER | RIDGE_LOGISTIC | 1251 | 0.6099 | 0.4535 | 0.1437 | 0.8638 | 0.9009 | 0.0576 |
| transit_given_episode_acceptance | FORWARD_TIME | NULL_PREVALENCE | 136 | 0.8382 | 0.4546 | 0.1384 | 0.3927 | 0.8030 | 0.1021 |
| transit_given_episode_acceptance | FORWARD_TIME | RIDGE_LOGISTIC | 136 | 0.8382 | 0.4324 | 0.1313 | 0.5829 | 0.8640 | 0.0898 |
| transit_given_episode_acceptance | GROUPED_RUN | NULL_PREVALENCE | 263 | 0.8631 | 0.4028 | 0.1190 | 0.4096 | 0.8221 | 0.0653 |
| transit_given_episode_acceptance | GROUPED_RUN | RIDGE_LOGISTIC | 263 | 0.8631 | 0.3886 | 0.1179 | 0.6758 | 0.9294 | 0.0656 |
| transit_given_episode_acceptance | INSTRUMENT_TRANSFER | NULL_PREVALENCE | 263 | 0.8631 | 0.4034 | 0.1191 | 0.4104 | 0.8424 | 0.0753 |
| transit_given_episode_acceptance | INSTRUMENT_TRANSFER | RIDGE_LOGISTIC | 263 | 0.8631 | 0.3962 | 0.1190 | 0.6357 | 0.9074 | 0.0844 |

## Nonlinear challenger gates

| target | status | grouped_logloss_improvement | forward_logloss_improvement | instrument_transfer_logloss_improvement |
| --- | --- | --- | --- | --- |
| reclaim_given_break | PASS_NONLINEAR_CHALLENGER | 0.0290 | 0.0215 | 0.0198 |
| initial_acceptance_given_initial_contact | PASS_NONLINEAR_CHALLENGER | 0.0557 | 0.0560 | 0.0628 |
| rejection_given_initial_contact | PASS_NONLINEAR_CHALLENGER | 0.2441 | 0.2567 | 0.2562 |
| retest_hold_given_retest_contact | PASS_NONLINEAR_CHALLENGER | 0.2196 | 0.2357 | 0.2237 |
| transit_given_episode_acceptance | HOLD_BASELINE_ONLY | 0.0142 | 0.0222 | 0.0072 |

## Candidate protocol

| target | status | selected_model_class | holdout_authorized | reason |
| --- | --- | --- | --- | --- |
| reclaim_given_break | FROZEN_RESEARCH_CANDIDATE | RIDGE_LOGISTIC | False | ridge is the hard baseline; nonlinear challenger was not uniformly superior |
| initial_acceptance_given_initial_contact | FROZEN_RESEARCH_CANDIDATE | RIDGE_LOGISTIC | False | ridge is the hard baseline; nonlinear challenger was not uniformly superior |
| rejection_given_initial_contact | FROZEN_RESEARCH_CANDIDATE | RIDGE_LOGISTIC | False | ridge is the hard baseline; nonlinear challenger was not uniformly superior |
| retest_hold_given_retest_contact | FROZEN_RESEARCH_CANDIDATE | BOOSTED_STUMPS | False | challenger beats ridge on grouped and forward log loss without material calibration loss |
| transit_given_episode_acceptance | NO_HOLDOUT_CANDIDATE | nan | False | baseline did not clear all stability and run-block uncertainty gates |

## Latent-state gate

```json
{
  "status": "DEFERRED_PROTOCOL_NOT_FROZEN",
  "transitions": 37495,
  "event_states": 16,
  "minimum_source_transitions": 198,
  "median_run_jsd_bits": 0.007711307731808103,
  "reason": "deterministic transition geometry is measured; latent state count and identification protocol must be pre-registered before fitting",
  "hmm_fit_performed": false
}
```

## Interpretation boundary

Observed separation is exploratory evidence of empirical structure, not a trading edge.
No model is authorized for the reserved holdout until its class and evaluation protocol are frozen.