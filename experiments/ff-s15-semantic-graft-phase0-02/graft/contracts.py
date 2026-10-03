from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

EXPERIMENT = Path(__file__).resolve().parents[1]
WORKSPACE = EXPERIMENT.parents[1]
BANK_CODE = WORKSPACE / "experiments" / "ff-s15-bank-01" / "src"
BANK = BANK_CODE.parent / "releases" / "BANK-v1"
NVME = Path(r"C:\phoenix-target-overgraph\semantic-graft-phase0-v02-20261001")
PARENT_NVME = Path(r"C:\phoenix-target-overgraph\semantic-graft-phase0-20261001")
PARENT_CONFIG_SHA256 = "0c580fbf7c00a9a1cd0d6d8ae438db1f3f0aebe5eab2adea9b13315cef724c46"
PARENT_ABI_SHA256 = "148c8b0900fc8168fd4f58d57f9c09138ca64296a12284e8ae782fd513224969"
PARENT_LOCK_SHA256 = "375225ccb9a4f5fd3b9a17ffda06707851de9b6cb93e9f22b0de1f6d05029f02"
CACHE_ROOT = Path(r"C:\phoenix-target-overgraph\lexi-h2-rebuild-20260930")
ENCODER_CACHE = Path(r"D:\codex-runs\encoder-contrast-01\primitives\encoder")
SUBSTRATES = ("causal_base", "ner_lora_step500", "nli_lora_step500", "encoder_base")
GLOBAL_TARGETS = (
    "solvable", "goal_satisfied", "missing_information_present",
    "contradiction_present", "requestable_information_present",
    "number_or_structure_of_missing_requirements",
)
CANDIDATE_TARGETS = (
    "candidate_legal", "candidate_satisfies_goal", "candidate_supported",
    "candidate_has_counterevidence", "candidate_has_unmet_requirements",
    "candidate_applicable", "candidate_requires_missing_information",
)
GLOBAL_AVAILABLE = (False, True, True, True, False, True)
CANDIDATE_AVAILABLE = (True, True, False, False, False, False, False)
ACTION_TYPES = ("PAD", "MOVE", "ACTIVATE", "DEACTIVATE", "WAIT", "NOOP")
ARGUMENT_ROLES = ("entity", "src", "dst", "target")
OBSERVATION_FIELDS = ("input_text", "goal", "bindings")
IDENTITY_FIELDS = ("world_id", "paired_world", "surface_family", "world_hash")


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canon_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)
                         + "\n", encoding="utf-8")
    temporary.replace(path)


def simulator():
    spec = importlib.util.spec_from_file_location("phase0_bank_simulator", BANK_CODE / "simulator.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def supervision_abi() -> dict:
    global_sources = (
        (None, "UNAVAILABLE", "Unrestricted solvability is not certified by depth-four planning."),
        ("simulator.goal_satisfied(initial_state, goal)", "SIMULATOR_TRUTH", "Goal holds in current canonical state."),
        ("bool(world.missing_information)", "GENERATOR_ANNOTATION", "Missing-information annotation exists; not inferred action relevance."),
        ("bool(world.contradictions)", "GENERATOR_ANNOTATION", "Canonical contradiction annotation exists."),
        (None, "UNAVAILABLE", "Random ASK choice does not define requestability or negative labels."),
        ("len(world.missing_information)", "GENERATOR_ANNOTATION", "Scalar annotation-count proxy only: BANK-v1 0/1; includes unknown entity annotations; not full precondition structure."),
    )
    candidate_sources = (
        ("simulator.legal_actions(initial_state, available_actions)", "SIMULATOR_TRUTH", "Canonical simulator legality, not observation justification."),
        ("legal(a) and simulator.goal_satisfied(simulator.apply_action(initial_state,a),goal)", "SIMULATOR_TRUTH", "Legal one-step goal achievement, including WAIT/NOOP when goal already holds."),
        (None, "UNAVAILABLE", "No canonical candidate support evaluator."),
        (None, "UNAVAILABLE", "Global contradictions have no canonical candidate attribution."),
        (None, "UNAVAILABLE", "Global missing annotations have no candidate requirement mapping."),
        (None, "UNAVAILABLE", "No independent applicability contract; do not alias legality."),
        (None, "UNAVAILABLE", "No canonical candidate-to-missing-information dependency."),
    )
    def entries(names, availability, sources):
        return [{"name": n, "available": a, "source": s[0], "supervision_provenance": s[1],
                 "meaning": s[2], "kind": "count" if n == GLOBAL_TARGETS[-1] else "binary"}
                for n, a, s in zip(names, availability, sources)]
    return {
        "schema": "frozen-fabrique.semantic-epistemic-supervision/v1",
        "global": entries(GLOBAL_TARGETS, GLOBAL_AVAILABLE, global_sources),
        "candidate": entries(CANDIDATE_TARGETS, CANDIDATE_AVAILABLE, candidate_sources),
        "unavailable_storage": "value=0 is padding only; availability mask=false excludes loss, metrics, and runtime estimates",
        "runtime": "estimate.semantic.* and estimate.candidate.* are MODEL_ESTIMATE only with attached trained graft artifact; unavailable ontology targets are never emitted as observed false",
        "truth": "Training/evaluation labels remain ORACLE_TRUTH or GENERATOR_ANNOTATION / UNAVAILABLE at runtime.",
        "action_endpoint": {"source": "world.selected_action if world.decision==ACT and exact action belongs to A",
                            "kind": "candidate_index", "provenance": "CANONICAL_POLICY_ENDPOINT",
                            "unavailable": "ASK/ABSTAIN or out-of-schema actions; never substitute WAIT/NOOP"},
        "truth_changing_contrast": {"score": "candidate_supported logit", "available": False,
                                   "reason": "No canonical candidate-supported labels or emitted truth-changing support pairs; no legality substitution"},
    }


def default_config() -> dict:
    return {
        "schema": "frozen-fabrique.semantic-graft-phase0-config/v2",
        "seed": 20261001, "substrates": list(SUBSTRATES),
        "surface": "final_plus_mean", "input_dim": 2048, "hidden_dim": 128,
        "semantic_dim": 64, "epistemic_dim": 64, "attention_heads": 4,
        "action_embedding_dim": 16, "argument_embedding_dim": 8,
        "max_entities": 64, "dropout": 0.0,
        "entity_local_dim": 1024, "entity_role_dim": 32,
        "fabrics": {"causal": "late integrated row-state + candidate-conditioned graft",
                    "encoder": "full-context row-state + existing final-layer entity-local graft"},
        "hidden_coordinate_alignment": False,
        "loss": {"lambda_S": 1.0, "lambda_E": 0.1, "lambda_A": 0.25,
                 "lambda_CF": 1.0, "lambda_R": 0.1, "contrast_margin": 1.0,
                 "supervised_reduction": "sum available coordinates/candidates per row, mean over eligible rows",
                 "action_reduction": "mean CE over canonical eligible ACT endpoints",
                 "contrast_reduction": "mean eligible directed support-pair hinge; no canonical eligible pairs in this phase",
                 "renderer_reduction": "mean pair squared semantic norm + aligned candidate squared norm averaged over candidates",
                 "renderer_pairs_per_batch": 8},
        "meaning_preserving_renderers": ["S0", "S1", "S2", "S3", "S4", "S6", "S7", "S8", "S10", "S11"],
        "candidate_schema": "BANK-v1-observable-bindings-action-enumerator/v1",
        "train_rows": 20000, "dev_rows": 2000,
        "population": "First rows in file order; paired renderings grouped by paired_world.",
        "training": {"epochs": 5, "batch_size": 64, "lr": 0.001,
                     "weight_decay": 0.0001, "gradient_clip": 1.0,
                     "checkpoint": "last epoch; no model/surface/width sweep",
                     "binary_loss": "masked BCEWithLogits", "count_loss": "masked SmoothL1",
                     "aggregation": "Shared five-term weighted objective; unavailable supervision masked",
                     "normalization": "TRAIN-only mean/std embedded in graft checkpoint"},
        "evaluation": {"threshold": 0.5, "count_rounding": "max(0,floor(raw+0.5))",
                       "bootstrap_seed": 20261001, "bootstrap_replicates": 1000,
                       "resampling_unit": "canonical paired_world; same draws across compared lanes",
                       "held_renderers": ["S7", "S8", "S9"],
                       "promotion": "No Phase0 promotion or System1.5 integration"},
    }
