"""Build the R3 immutable pre-run contract and execution-source lock."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r3-selectivity"
SEALS = EXP / "seals"
LOCK_PATH = SEALS / "r3-phase-packet-seal-v01.json"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03")
V02 = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02")
BASE = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01")
LFM = Path(r"D:\codex-runs\jev-lfm-variable-v07\models\lfm2.5-1.2b-base")
GEN_BIN = Path(r"C:\Users\shuga\AppData\Local\Temp\jev-r3-v03-generator-20260926.exe")

EXPECTED = {
    "exclusion_payload": "e206a995582cd47a50f5b6c6411f8660fafd985ab80a1620f4db4caed0066ac3",
    "exclusion_root": "89dab4a60209a7f5a11205926ed4839377923d534f1275d69e53c90bd5e32f47",
    "s80_pretraining_seal": "dcf3e524fc57cd359029bda2fc1a9e52b66d77843552394c778723aa34744396",
    "s120_calibration": "cd50ec49d5d2196cc92df0bb18276f2d10643d2cc5dc12b928dc6459bea16fab",
    "s120_root": "e727f13f404010068176f55fd14081978881027a15c27bde52ca97d5f63f2253",
    "replay_root": "f588bad0b6f8ebaadda5438b4f1e72ea9104b4483ddc77cd79d7fd633f4e08f3",
    "design_simulation": "e098f44cbe0cf7c95395f3559451221d71b9946fa7208961f8460849690c89f5",
    "design_simulation_seal": "5ada5a4f442dab7ad5e69ae16d8a91f009ac0c7e473fe3e29a4617f120382ef0",
    "balanced_primary": "8c75354d6225762e275552fcf279d65fb4870f382405bdbbccc36576a950a859",
    "balanced_sham": "98ec35a78fbf2a65d050b1086bbf6337acaaae743cd4208af89107d235247617",
    "reverse_sham": "d75104b5574ea52ad62fb0c72c1e778dc7d4f3da76d678cf2cb756fb39ec40d0",
    "training_features": "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6",
    "candidate_features": "3bb3036f455a83409361eb3e4150833bd8b255a2a783ec1218b00b12315c0590",
    "reverse_source": "d75104b5574ea52ad62fb0c72c1e778dc7d4f3da76d678cf2cb756fb39ec40d0",
    "bridge_primary": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
    "bridge_sham": "9dd346766856f56006be326c171e664dcbab23983cdd7501f480b6fabb6ff895",
    "training_scope": "aa8cba58f4a8ec46ed6ec8eaf0bfbe992b03b9fa58f815b4259d9fdfe2b009f3",
    "candidate_catalog": "1698ea2078951837b3cb780a3f873c3c099e5e3d001c714e1d58a41e2951487e",
    "probe": "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1",
    "batcher": "52033950dab23835c13f4aa74a2f0d5867aec754f8a139a63a739a36b0cb62b9",
    "objective": "fc412072592857be36b02312d852d08ce3df2bf6fa7b28f8c1d59575c28e1ea4",
    "lfm_adapter": "b8cd79a9a3265eca0fde5f509ba7c058bc2065d7747efe17ff7c7c1f6335b2d0",
}
MODEL_HASHES = {
    "config.json": "15d6157fb6df3f8272e2fe90e18f57727ccf02a125c94469198b0f3281510185",
    "model.safetensors": "7678ab9546a0c51c1fca161876b1efc4f0906277f170b5822045f40fdaf9eeff",
    "tokenizer.json": "d7a0ab0fc22e41ec8c6d7450a9ff9ce40e196ec5e5a2fa6a2105e064e0514ed7",
    "tokenizer_config.json": "8cba5b0c7acab23a0d4cc9ac587346c9220a1b6d288fc5346fe118202fd6f43e",
    "special_tokens_map.json": "742aefe2b7dec496e8caffdba03a75d0c1a9925d53bd3f3e0d388c96b591b6f4",
}


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def repo(path: str) -> Path:
    return ROOT / path


def source_rows() -> list[tuple[str, Path]]:
    source_dir = EXP / "source"
    rows = [
        ("R3 panel generator Rust entry", EXP / "generator-v03/src/main.rs"),
        ("R3 panel generator Cargo manifest", EXP / "generator-v03/Cargo.toml"),
        ("R3 panel generator Cargo lock", EXP / "generator-v03/Cargo.lock"),
        ("R3 panel generator tested Windows binary", GEN_BIN),
        ("base decision-world crate manifest", repo("experiments/jev-decision-world-v01/Cargo.toml")),
        ("base decision-world crate lock", repo("experiments/jev-decision-world-v01/Cargo.lock")),
        ("base decision-world exact source", repo("experiments/jev-decision-world-v01/src/exact.rs")),
        ("base decision-world families source", repo("experiments/jev-decision-world-v01/src/families.rs")),
        ("base decision-world generation source", repo("experiments/jev-decision-world-v01/src/generate.rs")),
        ("base decision-world library source", repo("experiments/jev-decision-world-v01/src/lib.rs")),
        ("base decision-world types source", repo("experiments/jev-decision-world-v01/src/types.rs")),
        ("base decision-world validator source", repo("experiments/jev-decision-world-v01/src/validate.rs")),
        ("inherited training family source", repo("experiments/jev-information-density-v08n/generator/src/families.rs")),
        ("inherited training generator source", repo("experiments/jev-information-density-v08n/generator/src/generator.rs")),
        ("R3 exclusion builder", source_dir / "build_r3_v03_exclusion_sets_v02.py"),
        ("R3 panel validator", source_dir / "validate_and_seal_r3_panel_v03.py"),
        ("R3 feature extractor", source_dir / "extract_r3_confirmatory_features_v01.py"),
        ("R3 feature repeat verifier", source_dir / "verify_and_seal_r3_feature_repeat_v01.py"),
        ("R3 schedule materializer", source_dir / "materialize_r3_training_schedule_v01.py"),
        ("R3 training runtime helper", source_dir / "run_r3_pretreatment_calibration_v01.py"),
        ("R3 training runner", source_dir / "run_r3_confirmatory_training_v01.py"),
        ("R3 target-free evaluator", source_dir / "evaluate_r3_confirmatory_matrix_v01.py"),
        ("R3 frozen analyzer", source_dir / "analyze_r3_confirmatory_v01.py"),
        ("R3 independent replay and result sealer", source_dir / "verify_r3_independent_replay_v01.py"),
        ("R3 phase lock builder", source_dir / "seal_r3_phase_packet_v01.py"),
        ("R3 design simulation implementation", source_dir / "simulate_r3_design_operating_characteristics_v01.py"),
        ("R3 continuation replay implementation", source_dir / "run_r3_continuation_replay_v01.py"),
        ("R3 S80 summary implementation", source_dir / "summarize_r3_pretreatment_s80_v01.py"),
        ("R3 S120 calibration runner", source_dir / "run_r3_calibration_step120_1x_v01.py"),
        ("R3 S120 calibration summarizer", source_dir / "summarize_r3_calibration_s120_1x_v02.py"),
        ("R3 candidate permutation sanity test", source_dir / "tests/test_r3_scorer_permutation_equivariance.py"),
        ("R3 schedule tests", source_dir / "tests/test_r3_training_schedule_v01.py"),
        ("R3 analysis tests", source_dir / "tests/test_r3_analysis_v01.py"),
        ("R3 independent replay tests", source_dir / "tests/test_r3_independent_replay_v01.py"),
        ("R3 exclusion parser tests", source_dir / "tests/test_r3_v03_exclusion_parser.py"),
        ("R3 exclusion construction tests", source_dir / "tests/test_r3_v03_exclusion_sets_v02.py"),
        ("frozen compatibility head", repo("experiments/jev-frozen-readout-v01/probe.py")),
        ("frozen batching implementation", repo("experiments/jev-frozen-scaling-v05/train_v05.py")),
        ("frozen weighted objective", repo("experiments/jev-information-density-v08q/source/q_weighted_objective_v02.py")),
        ("pinned LFM extractor adapter", repo("experiments/jev-lfm-variable-v07/extract_lfm.py")),
    ]
    return rows


def input_rows() -> list[tuple[str, Path, str | None]]:
    rows: list[tuple[str, Path, str | None]] = [
        ("sealed E1 identity exclusion payload", RUN / "identity-exclusions-v02/field-exclusion-domain-hashes.json", EXPECTED["exclusion_payload"]),
        ("sealed E1 exclusion provenance receipt", RUN / "identity-exclusions-v02/exclusion-receipt.json", None),
        ("sealed E1 exclusion root", RUN / "identity-exclusions-v02/root-seal.json", None),
        ("R3 balanced S80 pretraining seal", V02 / "calibration-preflight-v03/pretraining-seal.json", EXPECTED["s80_pretraining_seal"]),
        ("R3 balanced S80 calibration summary", V02 / "calibration-training-v02/pretreatment-s80-calibration-v02.json", None),
        ("R3 balanced S80 calibration seal", V02 / "calibration-training-v02/pretreatment-s80-calibration-v02-seal.json", None),
        ("R3 balanced 1x S120 calibration", V02 / "calibration-s1x-terminal-eval-v02/step120-s1x-calibration-v02.json", EXPECTED["s120_calibration"]),
        ("R3 balanced 1x S120 calibration root", V02 / "calibration-s1x-terminal-eval-v02/root-seal.json", EXPECTED["s120_root"]),
        ("R3 continuation exact-replay root", V02 / "continuation-replay-v02/replay-root-seal.json", EXPECTED["replay_root"]),
        ("R3 design simulation", V02 / "design-simulation-v03/design-operating-characteristics.json", EXPECTED["design_simulation"]),
        ("R3 design simulation seal", V02 / "design-simulation-v03/design-simulation-seal.json", EXPECTED["design_simulation_seal"]),
        ("balanced training primary occurrences", V02 / "calibration-inputs-v03/balanced-primary-occurrences.jsonl", EXPECTED["balanced_primary"]),
        ("balanced training SHAM events", V02 / "calibration-inputs-v03/balanced-sham-events.jsonl", EXPECTED["balanced_sham"]),
        ("reverse SHAM text manifest", V02 / "calibration-inputs-v03/reverse-sham-texts.jsonl", EXPECTED["reverse_source"]),
        ("sealed shared training feature tensor", BASE / "shared-feature-cache/shared-training-features.pt", EXPECTED["training_features"]),
        ("sealed candidate feature tensor", BASE / "phase-b-run-v01/feature-cache/candidate-features.pt", EXPECTED["candidate_features"]),
        ("bridge raw primary occurrence source", BASE / "phase-b-v03-inputs/common-primary-occurrence-manifest.jsonl", EXPECTED["bridge_primary"]),
        ("bridge raw SHAM source", BASE / "phase-b-v03-inputs/head-input-manifest-B-SHAM.jsonl", EXPECTED["bridge_sham"]),
        ("training-only feature scope", BASE / "shared-feature-cache/training-only-feature-scope.jsonl", EXPECTED["training_scope"]),
        ("sealed training candidate catalog", BASE / "phase-b-v03-inputs/candidate-catalog.json", EXPECTED["candidate_catalog"]),
    ]
    rows.extend((f"pinned LFM model file {name}", LFM / name, expected) for name, expected in MODEL_HASHES.items())
    return rows


def main() -> int:
    require(not LOCK_PATH.exists(), "R3 phase packet lock already exists; refusing rewrite")
    contracts = []
    contract_data: dict[str, dict[str, Any]] = {}
    for name, relative in (("run", "contracts/r3-v03-run-contract.json"),
        ("panel", "contracts/r3-v03-panel-contract.json"),
        ("analysis", "contracts/r3-v03-analysis-contract.json")):
        path = EXP / relative
        contract = json.loads(path.read_text(encoding="utf-8"))
        require(contract.get("status") == "SEALED", f"R3 {name} contract is not sealed")
        contract_data[name] = contract
        contracts.append({"name": name, "path": str(path.resolve()), "sha256": sha_file(path)})
    run_contract, panel_contract, analysis_contract = (contract_data[name] for name in ("run", "panel", "analysis"))
    require(run_contract["cohort"]["balanced_histories"] == 192
        and run_contract["cohort"]["bridge_count"] == 24
        and run_contract["training"]["steps"] == 120
        and run_contract["training"]["checkpoints"] == [80, 100, 120]
        and run_contract["training"]["late_branches"] == [1.0, 0.5],
        "sealed R3 run contract differs from the authorized packet")
    require(panel_contract["construction"]["neighborhoods"] == 2_000
        and panel_contract["construction"]["neighborhoods_per_family_direction"] == 250
        and panel_contract["construction"]["directions"] == ["high_to_low", "low_to_high"]
        and panel_contract["features"]["backbone_revision"] == "7453bca97ca1e67754c4035a4b4c584e1c9dd725",
        "sealed R3 panel contract differs from the authorized packet")
    require(analysis_contract["ratio"]["S_min"] == 0.01
        and analysis_contract["ratio"]["eligible_count_minimum"] == 173
        and [row["step"] for row in analysis_contract["fixed_sequence"]] == [1, 2, 3, 4],
        "sealed R3 analysis contract differs from the authorized packet")

    execution_sources = []
    for name, path in source_rows():
        require(path.is_file(), f"locked execution source absent: {path}")
        observed = sha_file(path)
        if name == "frozen compatibility head":
            require(observed == EXPECTED["probe"], "frozen probe hash differs from training contract")
        elif name == "frozen batching implementation":
            require(observed == EXPECTED["batcher"], "frozen batcher hash differs from training contract")
        elif name == "frozen weighted objective":
            require(observed == EXPECTED["objective"], "frozen objective hash differs from training contract")
        elif name == "pinned LFM extractor adapter":
            require(observed == EXPECTED["lfm_adapter"], "pinned LFM adapter hash mismatch")
        execution_sources.append({"name": name, "path": str(path.resolve()), "sha256": observed,
            "bytes": path.stat().st_size})

    sealed_inputs = []
    for name, path, expected in input_rows():
        require(path.is_file(), f"sealed pre-run input absent: {path}")
        observed = sha_file(path)
        require(expected is None or observed == expected, f"bound pre-run input hash mismatch: {name}")
        sealed_inputs.append({"name": name, "path": str(path.resolve()), "sha256": observed,
            "bytes": path.stat().st_size, "expected_sha256": expected})

    exclusion_root = json.loads((RUN / "identity-exclusions-v02/root-seal.json").read_text(encoding="utf-8"))
    require(exclusion_root.get("entries_root_sha256") == EXPECTED["exclusion_root"],
        "v05 denylist exclusion root identity mismatch")
    s120 = json.loads((V02 / "calibration-s1x-terminal-eval-v02/step120-s1x-calibration-v02.json").read_text(encoding="utf-8"))
    require(s120.get("history_count") == 48
        and s120.get("floor_feasibility", {}).get("0.01", {}).get("step120_1x_floor_count") == 48,
        "S120 calibration did not attest all 48 histories; inspect sealed summary")
    simulation = json.loads((V02 / "design-simulation-v03/design-operating-characteristics.json").read_text(encoding="utf-8"))
    n192 = next((row for row in simulation.get("decision_operating_characteristics", [])
        if row.get("n_histories") == 192), None)
    require(n192 is not None, "design simulation lacks the locked 192-history cohort")
    r_scenarios = {round(float(row["attenuation_fraction"]), 6): row
        for row in n192["median_interval_scenarios"]}
    coverage_scenarios = {round(float(row["attenuation_fraction"]), 6): row
        for row in simulation.get("ratio_coverage_sensitivity", [])
        if row.get("n") == 192 and row.get("candidate_S_min") == 0.01}
    require(0.0 in r_scenarios and 0.1 in r_scenarios and 0.1 in coverage_scenarios
        and 0.2 in coverage_scenarios
        and "R_median_upper_below_zero_probability" in r_scenarios[0.1],
        "design simulation omits null/10%-attenuation R operating characteristics")

    analysis_sources = [row for row in execution_sources if row["name"] in (
        "R3 frozen analyzer", "R3 independent replay and result sealer")]
    body: dict[str, Any] = {
        "schema": "jev-r3-phase-packet-lock-v01",
        "identity": "JEV-V08Q-R3-SELECTIVITY-V03",
        "status": "SEALED_AUTHORIZED_FOR_PHASE_EXECUTION",
        "authorization_basis": "User authorized one complete phase-sized R3 execution; successful frozen prerequisites advance automatically.",
        "contracts": contracts,
        "execution_sources": execution_sources,
        "sealed_inputs": sealed_inputs,
        "analysis_sources": [{"name": row["name"], "sha256": row["sha256"]} for row in analysis_sources],
        "design_basis": {
            "balanced_s80_pretraining_seal_sha256": EXPECTED["s80_pretraining_seal"],
            "balanced_s120_1x_calibration_sha256": EXPECTED["s120_calibration"],
            "continuation_replay_root_sha256": EXPECTED["replay_root"],
            "design_operating_characteristics_sha256": EXPECTED["design_simulation"],
            "S120_floor_feasibility": {"n": 48,
                "eligible_at_S_min_0_01": s120["floor_feasibility"]["0.01"]["step120_1x_floor_count"],
                "median_S_1x": s120["S120_1X_distribution"]["median"],
                "minimum_S_1x": s120["S120_1X_distribution"]["min"],
                "interpretation": "Outcome-blind calibration feasibility only; not a coverage guarantee or confirmatory result."},
            "simulation_R_median_upper_below_zero_probability": {
                "null": r_scenarios[0.0]["R_median_upper_below_zero_probability"],
                "10pct_attenuation": r_scenarios[0.1]["R_median_upper_below_zero_probability"]},
            "simulation_173_of_192_ratio_coverage_probability_at_Smin_0_01": {
                "10pct_attenuation": coverage_scenarios[0.1]["P_coverage_ge_90pct"],
                "20pct_attenuation": coverage_scenarios[0.2]["P_coverage_ge_90pct"]},
        },
        "execution_scope": {"panel_neighborhoods": 2_000, "panel_rows": 4_000,
            "balanced_histories": 192, "bridge_histories": 24, "training_histories_total": 216,
            "continuations": 432, "checkpoint_steps": [80, 100, 120],
            "prediction_cells": 1_080, "prediction_rows": 4_320_000,
            "raw_logit_shape": [1_080, 4_000, 4], "raw_logit_dtype": "little-endian float32",
            "panel_openings": 1, "targets_read_before_prediction_seal": False},
        "firewall": {"training_feedback_from_evaluation": False, "checkpoint_selection": False,
            "heldout_target_join_opened_only_after_prediction_seal": True,
            "calibration_histories_join_confirmatory_cohort": False,
            "E1_metrics_predictions_or_features_are_R3_inputs": False},
        "preservation": {"failed_prior_attempts_modified": False,
            "R2_or_R3_endpoint_reinterpretation": False, "result_label": "JEV-V08Q-R3-SELECTIVITY-V03"},
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    lock = {**body, "contract_bundle_root_sha256": hashlib.sha256(canonical).hexdigest()}
    SEALS.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("xb") as stream:
        stream.write((json.dumps(lock, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        stream.flush()
        import os
        os.fsync(stream.fileno())
    print(json.dumps({"status": lock["status"], "contract_bundle_root_sha256": lock["contract_bundle_root_sha256"],
        "contracts": contracts, "execution_source_count": len(execution_sources),
        "sealed_input_count": len(sealed_inputs), "lock_path": str(LOCK_PATH)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
