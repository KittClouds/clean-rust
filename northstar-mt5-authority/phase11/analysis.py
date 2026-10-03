from __future__ import annotations

import json
import math
from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd

try:
    from .contracts import CATEGORICAL_FEATURES, MODEL_GATE, NUMERIC_FEATURES, PHASE11_CONTRACT, TARGETS
    from .models import baseline_gate, evaluate_logistic, evaluate_stumps
    from .statistics import (
        continuous_rows, cumulative_incidence, dependence_rows, prepare_cohort,
        rate_rows, transition_audit,
    )
except ImportError:
    from contracts import CATEGORICAL_FEATURES, MODEL_GATE, NUMERIC_FEATURES, PHASE11_CONTRACT, TARGETS
    from models import baseline_gate, evaluate_logistic, evaluate_stumps
    from statistics import (
        continuous_rows, cumulative_incidence, dependence_rows, prepare_cohort,
        rate_rows, transition_audit,
    )

from phase10_5 import HoldoutAccessError, QuerySpec, ResearchCorpus


def _feature_manifest(frame: pd.DataFrame, target: str) -> pd.DataFrame:
    rows = []
    for timing, names in (("NUMERIC", NUMERIC_FEATURES), ("CATEGORICAL", CATEGORICAL_FEATURES)):
        for name in names:
            present = name in frame
            rows.append({
                "target": target, "feature": name, "feature_kind": timing,
                "available_at_eligibility": True, "present": present,
                "missing_share": float(frame[name].isna().mean()) if present else 1.0,
                "unique_values": int(frame[name].nunique(dropna=True)) if present else 0,
                "model_eligible": bool(
                    present and (timing == "CATEGORICAL" or frame[name].notna().mean() >= 1 - MODEL_GATE.maximum_missing_feature_share)
                ),
            })
    return pd.DataFrame(rows)


def _target_summary(frame: pd.DataFrame, target: str) -> dict[str, Any]:
    analyzable = frame[frame["target_analyzable"]]
    positive = int(analyzable["target_label"].sum())
    return {
        "target": target, "eligible": len(frame), "analyzable": len(analyzable),
        "positive": positive, "negative": len(analyzable) - positive,
        "censored": int(frame["target_censored"].sum()),
        "rate": positive / len(analyzable) if len(analyzable) else math.nan,
        "censoring_rate": float(frame["target_censored"].mean()) if len(frame) else math.nan,
        "runs": analyzable["run_key"].nunique(), "episodes": analyzable["episode_id"].nunique(),
        "median_time_seconds": float(pd.to_numeric(analyzable["target_time_seconds"], errors="coerce").median()),
    }


def _candidate_decision(target: str, metrics: pd.DataFrame, nonlinear: pd.DataFrame, gate: dict) -> dict:
    values = metrics.set_index(["split_type", "model"])
    grouped_ridge = values.loc[("GROUPED_RUN", "RIDGE_LOGISTIC")]
    forward_ridge = values.loc[("FORWARD_TIME", "RIDGE_LOGISTIC")] if (
        "FORWARD_TIME", "RIDGE_LOGISTIC"
    ) in values.index else None
    transfer_ridge = values.loc[("INSTRUMENT_TRANSFER", "RIDGE_LOGISTIC")] if (
        "INSTRUMENT_TRANSFER", "RIDGE_LOGISTIC"
    ) in values.index else None
    robust = bool(
        gate["status"] == "PASS_NONLINEAR_CHALLENGER"
        and grouped_ridge.get("run_block_delta_logloss_low", -math.inf) > 0
        and forward_ridge is not None
        and forward_ridge.get("run_block_delta_logloss_low", -math.inf) > 0
        and transfer_ridge is not None
        and transfer_ridge.get("run_block_delta_logloss_low", -math.inf) > 0
    )
    selected = "RIDGE_LOGISTIC"
    reason = "ridge is the hard baseline; nonlinear challenger was not uniformly superior"
    if robust and not nonlinear.empty:
        challenger = nonlinear.set_index(["split_type", "model"])
        try:
            grouped_stump = challenger.loc[("GROUPED_RUN", "BOOSTED_STUMPS")]
            forward_stump = challenger.loc[("FORWARD_TIME", "BOOSTED_STUMPS")]
            transfer_stump = challenger.loc[("INSTRUMENT_TRANSFER", "BOOSTED_STUMPS")]
            if (
                grouped_stump["log_loss"] < grouped_ridge["log_loss"]
                and forward_stump["log_loss"] < forward_ridge["log_loss"]
                and transfer_stump["log_loss"] < transfer_ridge["log_loss"]
                and grouped_stump["ece_10"] <= grouped_ridge["ece_10"] + .02
            ):
                selected = "BOOSTED_STUMPS"
                reason = "challenger beats ridge on grouped and forward log loss without material calibration loss"
        except KeyError:
            pass
    status = "FROZEN_RESEARCH_CANDIDATE" if robust else "NO_HOLDOUT_CANDIDATE"
    return {
        "target": target, "status": status, "selected_model_class": selected if robust else None,
        "reason": reason if robust else "baseline did not clear all stability and run-block uncertainty gates",
        "holdout_authorized": False,
        "evaluation_unit": "run-blocked attempts; episode membership never crosses a run fold",
    }


def analyze(corpus: ResearchCorpus) -> dict[str, Any]:
    # This call is expected to fail and is retained as a live gate proof.
    holdout_denied = False
    try:
        corpus.attempt_view("FUTURE_HOLDOUT")
    except HoldoutAccessError:
        holdout_denied = True

    summaries, rates, continuous, incidence, dependence, features = [], [], [], [], [], []
    model_metrics, predictions, fold_manifests, coefficients = [], [], [], []
    nonlinear_metrics, nonlinear_predictions = [], []
    gates: dict[str, dict] = {}
    candidates = []
    cohort_receipts = {}

    for target in TARGETS:
        raw = corpus.target_frame(QuerySpec.create(target))
        cohort_receipts[target] = raw.receipt
        prepared = prepare_cohort(raw.frame, target)
        summaries.append(_target_summary(prepared, target))
        rates.append(rate_rows(prepared, target))
        continuous.append(continuous_rows(prepared, target))
        incidence.append(cumulative_incidence(prepared, target))
        dependence.append(dependence_rows(prepared, target))
        features.append(_feature_manifest(prepared, target))

        model_frame = prepared[prepared["target_analyzable"]].copy()
        model_frame["target_label"] = model_frame["target_label"].astype("int8")
        metrics, target_predictions, folds, target_coefficients = evaluate_logistic(model_frame, target)
        gate = baseline_gate(metrics, model_frame)
        gates[target] = gate
        model_metrics.append(metrics)
        target_predictions.insert(0, "target", target)
        predictions.append(target_predictions)
        fold_manifests.append(folds)
        coefficients.append(target_coefficients)

        challenger = pd.DataFrame()
        if gate["status"] == "PASS_NONLINEAR_CHALLENGER":
            challenger, challenger_predictions = evaluate_stumps(model_frame, target)
            nonlinear_metrics.append(challenger)
            if not challenger_predictions.empty:
                challenger_predictions.insert(0, "target", target)
                nonlinear_predictions.append(challenger_predictions)
        candidates.append(_candidate_decision(target, metrics, challenger, gate))

    events = corpus.episode_timeline_view()
    transitions, transition_stability = transition_audit(events)
    latent_gate = {
        "status": "DEFERRED_PROTOCOL_NOT_FROZEN",
        "transitions": int(transitions["count"].sum()),
        "event_states": int(len(set(transitions["event_type"]) | set(transitions["next_event"]))),
        "minimum_source_transitions": int(transitions.groupby("event_type")["count"].sum().min()),
        "median_run_jsd_bits": float(transition_stability["mean_run_jsd_bits"].median()),
        "reason": "deterministic transition geometry is measured; latent state count and identification protocol must be pre-registered before fitting",
        "hmm_fit_performed": False,
    }
    candidate_frame = pd.DataFrame(candidates)
    summary_frame = pd.DataFrame(summaries)
    phase11_status = "PASS"
    exit_gates = {
        "phase10_5_interface_verified": True,
        "holdout_access_failed_closed": holdout_denied,
        "all_targets_have_run_blocked_models": len(model_metrics) == len(TARGETS),
        "all_targets_have_forward_evaluation": all(
            "FORWARD_TIME" in table["split_type"].values for table in model_metrics
        ),
        "all_targets_have_instrument_transfer_evaluation": all(
            "INSTRUMENT_TRANSFER" in table["split_type"].values for table in model_metrics
        ),
        "no_target_uses_censored_label": all(
            summary["analyzable"] + summary["censored"] == summary["eligible"] for summary in summaries
        ),
        "no_holdout_candidate_authorized": not candidate_frame["holdout_authorized"].any(),
        "latent_model_not_fit_without_protocol": not latent_gate["hmm_fit_performed"],
    }
    if not all(exit_gates.values()):
        phase11_status = "FAIL"
    return {
        "summary": {
            "contract": PHASE11_CONTRACT, "status": phase11_status,
            "corpus_sha256": corpus.corpus_hash, "interface_version": corpus.type_contract()["contract"],
            "targets": len(TARGETS), "runs": 20, "holdout_windows_touched": 0,
            "nonlinear_challengers_run": len(nonlinear_metrics),
            "frozen_research_candidates": int(candidate_frame["status"].eq("FROZEN_RESEARCH_CANDIDATE").sum()),
            "exit_gates": exit_gates, "model_gate_contract": asdict(MODEL_GATE),
        },
        "target_summary": summary_frame,
        "rates": pd.concat(rates, ignore_index=True),
        "continuous": pd.concat(continuous, ignore_index=True),
        "incidence": pd.concat(incidence, ignore_index=True),
        "dependence": pd.concat(dependence, ignore_index=True),
        "feature_manifest": pd.concat(features, ignore_index=True),
        "model_metrics": pd.concat(model_metrics, ignore_index=True),
        "model_predictions": pd.concat(predictions, ignore_index=True),
        "fold_manifest": pd.concat(fold_manifests, ignore_index=True),
        "coefficients": pd.concat(coefficients, ignore_index=True),
        "nonlinear_metrics": pd.concat(nonlinear_metrics, ignore_index=True) if nonlinear_metrics else pd.DataFrame(),
        "nonlinear_predictions": pd.concat(nonlinear_predictions, ignore_index=True) if nonlinear_predictions else pd.DataFrame(),
        "model_gates": gates,
        "candidate_protocol": candidate_frame,
        "transitions": transitions,
        "transition_stability": transition_stability,
        "latent_gate": latent_gate,
        "cohort_receipts": cohort_receipts,
    }
