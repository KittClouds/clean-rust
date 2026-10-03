"""Read-only contract audit and optional sealing for the v0.8N Phase-B packet.

This tool never loads the LFM model, state/candidate feature tensors, held-out
panel bodies, NewTight, or Phoenix.  It validates training-side manifests and
sealed metadata receipts only.  Use --seal-packet only after an independent
review has completed; sealing refuses to overwrite any packet artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PHASE_B = ROOT / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01")
INPUTS = RUN / "phase-b-v03-inputs"
PACKET = RUN / "phase-b-authorization-packet-v01"
EVAL = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-eval-panel-v01")
FEATURE_CACHE_RECEIPT = RUN / "shared-feature-cache/shared-feature-cache-receipt.json"
K_SUMMARY = Path(
    r"D:\codex-runs\jev-information-density-v08k\phase-b-v01\reports\k-attribution-summary.json"
)

EXPECTED = {
    "final_v09": "e86f3cd925841c4e68f8558696e68cb729b9b9ba49a644b9bc35e7e2bcde68a6",
    "phase_b_v02": "efb2bbe59293d7899083927cc187a292b5dfd1dc2948a0b752b3d9cbae2fd18d",
    "execution_receipt": "c022befafd49a1e317f692ff3b6f7efcccd11aee98285ca5f0071f6edbaf817c",
    "execution_tree": "f0fbae87a5e30902634108b0829d5da9a76bc691eb6a7551b0eebe4764cbbc77",
    "preflight": "b3101ce2c89df575628d5413f289a94f9fdee5a6e178ee77020143adaf15881c",
    "primary": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
    "catalog": "1698ea2078951837b3cb780a3f873c3c099e5e3d001c714e1d58a41e2951487e",
    "schedule": "4acfdc057ead9f07c310cfed452a385e5637bae2d367eac5d62343ceec892df7",
    "candidate_text": "36e4bd10d7f35b9ffcb5344cae2ca26adea51647830faf4659890f0dc811485e",
    "feature_cache_receipt": "d98ae657e28b976f187d4d67e58119ce80496e76c061c90362ac2e50ff7f720e",
    "heldout_seal": "425cef320df94e2b47b448203f8a916ebcbb2019539b2d09e51f5b4ced92f614",
    "heldout_validation": "d64f13904a739c0dc6485ba41362e26fe47ac3ab78ed8e2c7a2a8a897f663a85",
    "heldout_tree": "fc0adf7f8d1b9a10914dd9aa85282a42b0cd4bbe185f8b09710498b556d0f08f",
    "firewall": "79d25ac82fba1bc6332e16d8bc5f877fadd11cccaed5ef3f07eacfe5e1877da2",
    "k_summary": "acd86b65aaf3e349e24079a46b9aad865d4df0fd4b867b70b14d600029b45463",
}

ARM_INPUT_HASHES = {
    "B-DUP": "f6f4ec519a04efeac02962c68c2d2d8ec92cf43d25bb9fd974f168e67c4d3b2b",
    "B-MATCHED": "bd38446c0328f8092dc3293090fd3041d7be5d53945df6f80fb3770244d87b0d",
    "B-SHAM": "9dd346766856f56006be326c171e664dcbab23983cdd7501f480b6fabb6ff895",
}

ARMS = ("B-DUP", "B-MATCHED", "B-SHAM")
SEEDS = (20260927, 20260928, 20260929)
FAMILIES = (
    "exposure_control",
    "respiratory_monitoring",
    "salinity_control",
    "vibration_monitoring",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


class Audit:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.failures: list[str] = []
        self.files: dict[str, dict[str, Any]] = {}

    def check(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append({"name": name, "pass": bool(ok), "detail": detail})
        if not ok:
            self.failures.append(f"{name}: {detail}")

    def file(self, name: str, path: Path, expected: str | None = None) -> str:
        if not path.is_file():
            self.check(f"file:{name}", False, f"missing: {path}")
            return ""
        actual = sha256_file(path)
        ok = expected is None or actual == expected.lower()
        self.check(f"sha256:{name}", ok, f"{actual} at {path}")
        self.files[name] = {
            "path": str(path.resolve()),
            "sha256": actual,
            "size_bytes": path.stat().st_size,
        }
        return actual


def candidate_rows(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    rows = catalog["rows"]
    result: list[dict[str, Any]] = []
    for index, item in enumerate(rows):
        text = f"{item['name']} — {item['description']}"
        result.append(
            {
                "index": index,
                "candidate_semantic_id": str(item["candidate_semantic_id"]),
                "profile": "name_definition",
                "name": str(item["name"]),
                "description": str(item["description"]),
                "model_input_text": text,
                "model_input_utf8_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "feature_key": "mean_full@16",
                "expected_feature_dimension": 2048,
                "expected_feature_dtype": "float32",
            }
        )
    return result


def canonical_jsonl(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )


def surface_pair(anchor: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    anchor_text = anchor["text"]
    source_text = source["text"]
    anchor_lines = anchor_text.splitlines()
    source_lines = source_text.splitlines()
    changed = [
        (index, left, right)
        for index, (left, right) in enumerate(zip(anchor_lines, source_lines))
        if left != right
    ]
    changed_characters = sum(left != right for left, right in zip(anchor_text, source_text)) + abs(
        len(anchor_text) - len(source_text)
    )
    return {
        "same_character_length": len(anchor_text) == len(source_text),
        "same_whitespace_token_count": len(anchor_text.split()) == len(source_text.split()),
        "one_changed_line": len(anchor_lines) == len(source_lines) and len(changed) == 1,
        "one_changed_character": changed_characters == 1,
        "changed_line_number": changed[0][0] + 1 if len(changed) == 1 else None,
        "changed_field": changed[0][1].split(":", 1)[0] if len(changed) == 1 else None,
        "whitespace_tokens_before_changed_field": len("\n".join(anchor_lines[: changed[0][0]]).split()) if len(changed) == 1 else None,
    }


def verify() -> tuple[Audit, dict[str, Any]]:
    audit = Audit()
    run_path = PHASE_B / "phase-b-run-contract-v01.json"
    analysis_path = PHASE_B / "phase-b-analysis-contract-v01.json"
    frozen_path = PHASE_B / "phase_b-contract-v02.json"
    final_path = RUN / "synthesis/v08n-synthesis-receipt-final-v09.json"
    exec_receipt_path = INPUTS / "execution-inputs-receipt.json"
    exec_tree_path = INPUTS / "execution-inputs-hash-tree.json"
    preflight_path = RUN / "phase-b-preflight-v02/preflight-report.json"
    primary_path = INPUTS / "common-primary-occurrence-manifest.jsonl"
    catalog_path = INPUTS / "candidate-catalog.json"
    schedule_path = INPUTS / "fixed-training-schedule.jsonl"
    candidate_path = PACKET / "candidate-model-input-manifest.jsonl"
    arm_paths = {
        arm: INPUTS / f"head-input-manifest-{arm}.jsonl" for arm in ARMS
    }
    arm_hashes = {
        arm: audit.file(f"head_input_{arm}", path, ARM_INPUT_HASHES[arm])
        for arm, path in arm_paths.items()
    }
    scope_path = RUN / "shared-feature-cache/training-only-feature-scope.jsonl"
    state_features_path = RUN / "shared-feature-cache/shared-training-features.pt"
    firewall_path = EVAL / "seal/evaluation-firewall-lock.json"
    panel_seal_path = EVAL / "seal/seal-manifest.json"
    panel_validation_path = EVAL / "seal/independent-validation.json"
    panel_tree_path = EVAL / "seal/heldout-panel-hash-tree.json"

    run_sha = audit.file("run_contract", run_path)
    analysis_sha = audit.file("analysis_contract", analysis_path)
    audit.file("final_v09", final_path, EXPECTED["final_v09"])
    audit.file("phase_b_v02", frozen_path, EXPECTED["phase_b_v02"])
    audit.file("execution_receipt", exec_receipt_path, EXPECTED["execution_receipt"])
    audit.file("execution_hash_tree", exec_tree_path, EXPECTED["execution_tree"])
    audit.file("preflight_v02", preflight_path, EXPECTED["preflight"])
    audit.file("common_primary_manifest", primary_path, EXPECTED["primary"])
    audit.file("candidate_catalog", catalog_path, EXPECTED["catalog"])
    audit.file("fixed_schedule", schedule_path, EXPECTED["schedule"])
    audit.file("candidate_text_manifest", candidate_path, EXPECTED["candidate_text"])
    audit.file("k_summary", K_SUMMARY, EXPECTED["k_summary"])
    audit.file("training_feature_scope", scope_path)
    audit.file("training_feature_tensor", state_features_path, "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6")
    audit.file("training_feature_cache_receipt", FEATURE_CACHE_RECEIPT, EXPECTED["feature_cache_receipt"])
    audit.file("heldout_firewall_metadata", firewall_path, EXPECTED["firewall"])
    audit.file("heldout_seal_metadata", panel_seal_path, EXPECTED["heldout_seal"])
    audit.file("heldout_validation_metadata", panel_validation_path, EXPECTED["heldout_validation"])
    audit.file("heldout_hash_tree_metadata", panel_tree_path, EXPECTED["heldout_tree"])

    code_hashes = {
        "extractor": (
            ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py",
            "b8cd79a9a3265eca0fde5f509ba7c058bc2065d7747efe17ff7c7c1f6335b2d0",
        ),
        "head": (
            ROOT / "experiments/jev-frozen-readout-v01/probe.py",
            "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1",
        ),
        "batch_and_loss": (
            ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py",
            "52033950dab23835c13f4aa74a2f0d5867aec754f8a139a63a739a36b0cb62b9",
        ),
        "analysis_reference": (
            ROOT / "experiments/jev-information-density-v08i/phase_b/analyze_phase_b.py",
            "892939aaa4d3bd2d7868c18d411cab7ac4f9c03aaef9f0d4a1fdaadb7d39d06a",
        ),
    }
    for name, (path, expected) in code_hashes.items():
        audit.file(f"code_{name}", path, expected)
    audit.file("audit_script", Path(__file__))

    run = read_json(run_path)
    output_root = Path(run["output"]["root"])
    analysis = read_json(analysis_path)
    final = read_json(final_path)
    frozen = read_json(frozen_path)
    exec_receipt = read_json(exec_receipt_path)
    exec_tree = read_json(exec_tree_path)
    feature_receipt = read_json(FEATURE_CACHE_RECEIPT)
    preflight = read_json(preflight_path)
    firewall = read_json(firewall_path)
    panel_seal = read_json(panel_seal_path)
    panel_validation = read_json(panel_validation_path)
    catalog = read_json(catalog_path)

    audit.check("run_contract_state", run.get("phase_b_ready") is True and run.get("phase_b_authorized") is False and run.get("status") == "FROZEN_NOT_AUTHORIZED", "ready is not authorization")
    audit.check("analysis_contract_state", analysis.get("phase_b_ready") is True and analysis.get("phase_b_authorized") is False and analysis.get("status") == "FROZEN_NOT_AUTHORIZED", "analysis remains frozen and unauthorized")
    audit.check("final_v09_state", final.get("phase_b_ready") is True and final.get("phase_b_authorized") is False and final.get("promotable_for_training") is False, "sealed construction remains ready but non-authorized/non-promoted")
    audit.check("final_v09_model_boundaries", final.get("model_head_training") is False and final.get("evaluation_inference") is False and final.get("protected_evaluation_bodies_opened") is False and final.get("phoenix_access") is False, "final-v09 reports no model/evaluation/Phoenix contact")
    audit.check("final_v09_parent_hashes", final.get("phase_b_execution_inputs", {}).get("contract_hash_bound_in_tree") == EXPECTED["phase_b_v02"] and final.get("phase_b_execution_inputs", {}).get("receipt_sha256") == EXPECTED["execution_receipt"] and final.get("phase_b_preflight", {}).get("sha256") == EXPECTED["preflight"], "final-v09 pins the audited execution contract, inputs, and preflight")
    audit.check("run_parent_hashes", run["parents"]["construction_receipt"]["sha256"] == EXPECTED["final_v09"] and run["parents"]["phase_b_execution_contract"]["sha256"] == EXPECTED["phase_b_v02"] and run["parents"]["execution_input_receipt"]["sha256"] == EXPECTED["execution_receipt"] and run["parents"]["execution_input_hash_tree"]["sha256"] == EXPECTED["execution_tree"] and run["parents"]["preflight"]["sha256"] == EXPECTED["preflight"], "run-contract lineage matches materialized sealed receipts")
    audit.check("analysis_parents", analysis["parents"]["construction_receipt_sha256"] == EXPECTED["final_v09"] and analysis["parents"]["execution_contract_sha256"] == EXPECTED["phase_b_v02"] and analysis["parents"]["preflight_sha256"] == EXPECTED["preflight"], "analysis-contract lineage matches the sealed construction")
    audit.check(
        "analysis_binds_run",
        analysis["parents"]["run_contract"] == {
            "path": "experiments/jev-information-density-v08n/phase_b/phase-b-run-contract-v01.json",
            "sha256": run_sha,
        } and bool(run_sha),
        "analysis contract binds the exact finalized run-contract path and SHA-256",
    )

    audit.check("frozen_contract_identity", frozen.get("phase_b_authorized") is False and frozen.get("phase_b_ready") is True, "upstream v02 unchanged and still unauthorized")
    audit.check("execution_receipt_state", exec_receipt.get("common_across_arms") is True and exec_receipt.get("model_loaded") is False and exec_receipt.get("head_training") is False and exec_receipt.get("evaluation_inference") is False and exec_receipt.get("protected_evaluation_bodies_opened") is False and exec_receipt.get("phoenix_access") is False, "execution inputs were materialized without model or evaluation contact")
    audit.check("execution_tree_matches", exec_tree.get("contract") == EXPECTED["phase_b_v02"] and exec_tree.get("common_primary_occurrence_manifest") == EXPECTED["primary"] and exec_tree.get("candidate_catalog") == EXPECTED["catalog"] and exec_tree.get("fixed_training_schedule") == EXPECTED["schedule"] and all(exec_tree.get(f"head_input_{arm}") == ARM_INPUT_HASHES[arm] for arm in ARMS), "execution hash tree resolves to the frozen input identities and all three arm manifests")
    receipt_arm_hashes = exec_receipt.get("head_input_manifests", {})
    audit.check("execution_receipt_arm_manifests", all(receipt_arm_hashes.get(arm) == ARM_INPUT_HASHES[arm] for arm in ARMS), "execution-input receipt binds all three arm-specific head-input manifests")
    audit.check("preflight_state", preflight.get("status") == "V08N_PHASE_B_PREFLIGHT_PASS_READY_NOT_AUTHORIZED" and preflight.get("phase_b_ready") is True and preflight.get("phase_b_authorized") is False and preflight.get("model_contact") is False and preflight.get("evaluation_inference") is False and preflight.get("newtight_access") is False and preflight.get("phoenix_access") is False, "unchanged preflight passes while all contact gates remain closed")
    overlap = preflight.get("split_audit", {})
    audit.check("split_firewall", all(overlap.get(key) == 0 for key in ("train_eval_episode_overlap", "train_eval_input_hash_overlap", "train_eval_template_overlap", "generator_train_eval_family_overlap", "generator_train_eval_template_overlap")), "preflight reports zero train/evaluation identity, input, template, and family overlap")

    contract_training = run["training"]
    frozen_training = frozen["training"]
    frozen_model = frozen["model"]
    audit.check(
        "run_contract_semantics_match_v02",
        run["model_and_representation"]["repo_id"] == frozen_model["repo_id"]
        and run["model_and_representation"]["revision"] == frozen_model["revision"]
        and run["model_and_representation"]["backbone_frozen"] is frozen_model["backbone_frozen"] is True
        and run["model_and_representation"]["input_mode"] == "exact-length, single-row, no-padding"
        and run["model_and_representation"]["pooling"] == "final-layer mean_full over valid token positions"
        and run["head_input_and_architecture"]["projection_width"] == 128
        and run["head_input_and_architecture"]["trainable_parameters"] == 590_081
        and contract_training["seed_set"] == frozen_training["paired_seeds"]
        and contract_training["epochs"] == frozen_training["epochs"] == 3
        and contract_training["primary_batch_size"] == frozen_training["batch_size_groups"] == 256
        and contract_training["optimizer_steps_per_arm_seed"] == frozen_training["optimizer_steps_per_seed"] == 120
        and contract_training["optimizer"]["name"] == "torch.optim.AdamW"
        and contract_training["optimizer"]["learning_rate"] == frozen_training["learning_rate"] == 0.002
        and contract_training["optimizer"]["weight_decay"] == frozen_training["weight_decay"] == 0.01
        and contract_training["optimizer"]["scheduler"] == frozen_training["scheduler"] == "none"
        and contract_training["optimizer"]["gradient_clipping"] == frozen_training["gradient_clipping"] == "none"
        and contract_training["loss"]["auxiliary_weight"] == frozen["objective"]["auxiliary_event_weight"] == 1.0
        and contract_training["loss"]["step_normalization"] == frozen["objective"]["normalization"]
        and contract_training["primary_per_epoch"]["total_occurrences"] == frozen_training["primary_occurrence_count"]
        and contract_training["auxiliary_per_epoch"]["distinct_slots"] == frozen_training["auxiliary_event_count_per_arm"],
        "new run contract preserves the frozen Phase-B-v02 model, paired seeds, arm order, data budget, optimizer, and event semantics",
    )
    audit.check("seed_arm_design", tuple(contract_training["seed_set"]) == SEEDS and set(contract_training["arm_execution_order"]) == {str(seed) for seed in SEEDS} and contract_training["total_runs"] == 9 and contract_training["terminal_checkpoints"] == 9 and contract_training["epoch_checkpoints"] == 27, "three paired seeds, three arms, nine runs, 27 epoch checkpoints")
    expected_global_order = [f"{seed}/{arm}" for seed in SEEDS for arm in contract_training["arm_execution_order"][str(seed)]]
    audit.check("global_order", contract_training.get("global_execution_order") == expected_global_order and contract_training.get("concurrency") == "one run process at a time; no concurrent training runs", "fixed single-process global run order")
    audit.check("candidate_extraction_gate", run["candidate_feature_extraction"].get("first_model_contact_after_explicit_authorization") is True and run["candidate_feature_extraction"].get("candidate_text_manifest_sha256") == EXPECTED["candidate_text"] and run["candidate_feature_extraction"].get("expected_tensor_shape") == [48, 2048] and run["candidate_feature_extraction"].get("expected_dtype") == "contiguous float32", "candidate tensor extraction is the first post-authorization model contact and is strictly hash/shape gated")
    candidate_outputs = run["output"].get("candidate_feature_artifacts", {})
    expected_candidate_outputs = {
        "tensor_path": output_root / "feature-cache/candidate-features.pt",
        "token_length_receipt_path": output_root / "feature-cache/candidate-token-lengths.json",
        "feature_receipt_path": output_root / "feature-cache/candidate-feature-receipt.json",
    }
    audit.check("candidate_feature_artifact_handoff", all(Path(candidate_outputs.get(key, "")).resolve() == path.resolve() for key, path in expected_candidate_outputs.items()) and candidate_outputs.get("materialization_rule", "").startswith("create after explicit authorization") and all(not path.exists() for path in expected_candidate_outputs.values()), "candidate tensor/token-length/feature receipts have persistent fixed paths but remain absent before authorization")
    trainer_readable = run["evaluation_gate"]["training_process_filesystem_scope"]["readable"]
    trainer_feature_allowlist = all(any(name in item for item in trainer_readable) for name in ("candidate-features.pt", "candidate-feature-receipt.json", "candidate-token-lengths.json"))
    trainer_scope = run["evaluation_gate"]["training_process_filesystem_scope"].get("trainer_candidate_feature_scope", "")
    audit.check("candidate_feature_trainer_handoff", trainer_feature_allowlist and "may not read the candidate text manifest, tokenizer, model snapshot, or any evaluation path" in trainer_scope, "validated feature artifact and receipts are explicitly readable by trainers while source text/model/tokenizer/evaluation paths remain excluded")
    audit.check("candidate_path", Path(run["candidate_feature_extraction"]["only_input_source"]).resolve() == candidate_path.resolve(), "candidate extraction has one canonical absolute text-manifest source")
    declared_inputs = run["head_input_and_architecture"]["arm_input_manifests"]
    declared_arm_hashes_ok = all(
        declared_inputs.get(arm, {}).get("sha256") == ARM_INPUT_HASHES[arm]
        and Path(declared_inputs.get(arm, {}).get("path", "")).resolve() == arm_paths[arm].resolve()
        and declared_inputs.get(arm, {}).get("rows") == 15_000
        for arm in ARMS
    )
    declared_primary = declared_inputs.get("common_primary_occurrence_manifest", {})
    audit.check("run_contract_head_input_hashes", declared_arm_hashes_ok and declared_primary.get("sha256") == EXPECTED["primary"] and Path(declared_primary.get("path", "")).resolve() == primary_path.resolve(), "run contract explicitly binds each complete 15000-row arm manifest and the common primary stream")
    declared_scope = run["model_and_representation"].get("state_feature_scope_receipt", {})
    audit.check("run_contract_training_feature_scope", declared_scope.get("sha256") == EXPECTED["feature_cache_receipt"] and declared_scope.get("scope_rows") == 55_000 and declared_scope.get("scope_dimensions") == 2048 and declared_scope.get("source_scope") == "training_only", "run contract binds the pre-materialized training-only state feature scope and receipt")
    audit.check("training_feature_cache_receipt", feature_receipt.get("status") == "V08N_SHARED_FEATURE_CACHE_SEALED_TRAINING_ONLY" and feature_receipt.get("model", {}).get("revision") == run["model_and_representation"]["revision"] and feature_receipt.get("representation", {}).get("feature_key") == run["model_and_representation"]["feature_key"] and feature_receipt.get("scope", {}).get("sha256") == run["model_and_representation"]["state_feature_scope_sha256"] and feature_receipt.get("feature_tensor", {}).get("sha256") == run["model_and_representation"]["state_feature_source_sha256"] and feature_receipt.get("feature_tensor", {}).get("shape") == [55_000, 2048] and feature_receipt.get("head_training") is False and feature_receipt.get("evaluation_inference") is False and feature_receipt.get("protected_evaluation_bodies_opened") is False and feature_receipt.get("phoenix_access") is False, "training-only feature receipt agrees with the frozen model/repr identity and no-contact boundary")
    audit.check("run_recipe", run["model_and_representation"]["revision"] == "7453bca97ca1e67754c4035a4b4c584e1c9dd725" and contract_training["epochs"] == 3 and contract_training["primary_batch_size"] == 256 and contract_training["optimizer_steps_per_arm_seed"] == 120 and contract_training["precision"]["autocast"] is False and contract_training["loss"]["brier_weight"] == 0.25, "model, frozen head recipe, update budget, precision, and loss are pinned")
    audit.check("arm_definition", run["arms"]["order"] == list(ARMS) and run["arms"]["explicit_relation_loss"] is False and run["arms"]["all_other_training_events_identical"] is True, "only auxiliary source role/pointer differs")
    analysis_modifiers = analysis["estimands"]["secondary"].get("effect_modifiers", [])
    audit.check("analysis_surface_and_geometry_diagnostics", any("line/token position" in item for item in analysis_modifiers) and any("raw unnormalized head-input-space distances" in item for item in analysis_modifiers) and "does not isolate semantic identity from representation direction, higher-order geometry, or the deliberately different edited field/position" in analysis["sensitivity_guard_and_claim_rules"]["radius_only_interpretation_ceiling"] and "neutral_4 and neutral_5 only" in analysis["sensitivity_guard_and_claim_rules"]["matched_basis_scope"] and "without matching novel support or gradient-correlation structure" in analysis["sensitivity_guard_and_claim_rules"]["duplicate_control_scope"], "analysis records surface/location and full raw-feature geometry as diagnostics and limits claims to the selected neutral basis")

    primary = read_jsonl(primary_path)
    scope_rows = read_jsonl(scope_path)
    scope_by_episode = {row.get("episode_id"): row for row in scope_rows}
    scope_ok = (
        len(scope_rows) == 55_000
        and all(row.get("index") == index and str(row.get("neighborhood_id", "")).startswith("v08n-train-") for index, row in enumerate(scope_rows))
        and len(scope_by_episode) == 55_000
        and all(hashlib.sha256(row.get("text", "").encode("utf-8")).hexdigest() == row.get("input_sha256") for row in scope_rows)
    )
    audit.check("training_feature_scope_rows", scope_ok, "55000 indexed unique training-only feature inputs have exact text hashes; no held-out namespace appears")
    audit.check("primary_count_and_order", len(primary) == 10_000 and all(row.get("occurrence_index") == i for i, row in enumerate(primary)), "primary stream has 10000 explicitly indexed occurrences")
    primary_ids = [row.get("group_id") for row in primary]
    audit.check("primary_unique", len(set(primary_ids)) == 10_000, "every primary occurrence has a unique group identity")
    audit.check("primary_role_balance", sum(row.get("role") == "anchor" for row in primary) == 5_000 and sum(row.get("role") == "fact_flip" for row in primary) == 5_000, "primary stream contains 5000 anchors and 5000 fact flips")
    audit.check("primary_pair_adjacency", all(primary[i]["role"] == "anchor" and primary[i + 1]["role"] == "fact_flip" and primary[i]["neighborhood_id"] == primary[i + 1]["neighborhood_id"] for i in range(0, 10_000, 2)), "each anchor/fact pair occupies even/odd adjacent occurrence indices")
    anchor_rows = primary[::2]

    catalog_rows = candidate_rows(catalog)
    candidate_id_by_index = {index: row["candidate_semantic_id"] for index, row in enumerate(catalog_rows)}
    expected_candidate_bytes = canonical_jsonl(catalog_rows)
    actual_candidate_bytes = candidate_path.read_bytes()
    parsed_candidate_rows = [json.loads(line) for line in actual_candidate_bytes.splitlines() if line]
    audit.check("candidate_manifest_reconstruction", actual_candidate_bytes == expected_candidate_bytes and len(parsed_candidate_rows) == 48, "candidate text manifest exactly reconstructs from the sealed 48-row catalog")
    audit.check("catalog_semantic_order", [row["candidate_semantic_id"] for row in catalog_rows] == sorted(row["candidate_semantic_id"] for row in catalog_rows) and len({row["candidate_semantic_id"] for row in catalog_rows}) == 48, "candidate IDs are unique and lexicographically ordered")
    audit.check("candidate_catalog_spec", catalog.get("candidate_count") == 48 and catalog.get("feature_dimension") == 2048 and catalog.get("profile") == "name_definition" and catalog.get("index_order") == "lexicographic candidate_semantic_id", "frozen candidate catalog count/profile/dimension/order match the run contract")

    arm_rows: dict[str, list[dict[str, Any]]] = {}
    for arm in ARMS:
        rows = read_jsonl(arm_paths[arm])
        arm_rows[arm] = rows
        audit.check(f"{arm}_manifest_count", len(rows) == 15_000, "10000 common primary plus 5000 distinct auxiliary manifest rows")
        if len(rows) != 15_000:
            continue
        prim = rows[:10_000]
        aux = rows[10_000:]
        audit.check(f"{arm}_event_layout", all(row.get("event_kind") == "primary" and row.get("arm") == arm for row in prim) and all(row.get("event_kind") == "auxiliary" and row.get("arm") == arm for row in aux), "primary rows precede the auxiliary event segment")
        audit.check(f"{arm}_primary_identity", all(row.get("occurrence_index") == i and row.get("group_id") == primary[i].get("group_id") and row.get("feature_scope_index") == primary[i].get("feature_scope_index") and row.get("target_hash") == primary[i].get("target_hash") and row.get("candidate_semantic_ids") == primary[i].get("candidate_semantic_ids") for i, row in enumerate(prim)), "primary occurrence IDs, feature references, targets, and candidate IDs match the common stream")
        audit.check(f"{arm}_primary_masks", all(row.get("candidate_mask") == [True, True, True, True] and len(row.get("candidate_indices", [])) == 4 and all(isinstance(index, int) and 0 <= index < len(candidate_id_by_index) for index in row.get("candidate_indices", [])) and [candidate_id_by_index[index] for index in row.get("candidate_indices", [])] == row.get("candidate_semantic_ids") and row.get("state_feature_dimension") == 2048 and row.get("candidate_feature_dimension") == 2048 and len(row.get("target", [])) == 4 and abs(sum(row.get("target", [])) - 1.0) <= 1e-12 for row in prim), "primary events resolve four ordered candidate IDs through the catalog and raw 2048-dimensional state/candidate features with normalized targets")
        audit.check(f"{arm}_aux_slots", all(row.get("batch_slot") == slot and row.get("target_source_episode_id") == anchor_rows[slot].get("episode_id") and row.get("target_hash") == prim[2 * slot].get("target_hash") and row.get("candidate_semantic_ids") == prim[2 * slot].get("candidate_semantic_ids") and row.get("candidate_mask") == [True, True, True, True] for slot, row in enumerate(aux)), "each auxiliary slot maps to its corresponding anchor and carries the exact anchor target/schema")
        audit.check(f"{arm}_event_weights", all(row.get("loss_weight") == 1.0 and row.get("normalization") == "(N_base*L_base + N_aux*L_aux)/(N_base + N_aux)" for row in rows), "unit event weights and declared per-step normalization on every row")
        expected_role = {"B-DUP": "anchor_duplicate", "B-MATCHED": "matched_neutral", "B-SHAM": "certified_sham"}[arm]
        audit.check(f"{arm}_aux_role_source", all(row.get("auxiliary_source_role") == expected_role and ((arm == "B-DUP" and row.get("source_episode_id") == row.get("target_source_episode_id")) or (arm == "B-MATCHED" and "-neutral_" in str(row.get("source_episode_id"))) or (arm == "B-SHAM" and str(row.get("source_episode_id", "")).endswith("-sham"))) for row in aux), "arm auxiliary source identity matches its sealed treatment role")
        audit.check(f"{arm}_aux_dimensions", all(row.get("state_feature_dimension") == 2048 and row.get("candidate_feature_dimension") == 2048 and len(row.get("candidate_indices", [])) == 4 and all(isinstance(index, int) and 0 <= index < len(candidate_id_by_index) for index in row.get("candidate_indices", [])) and [candidate_id_by_index[index] for index in row.get("candidate_indices", [])] == row.get("candidate_semantic_ids") and len(row.get("target", [])) == 4 for row in aux), "auxiliary head inputs resolve the same four-candidate 2048-dimensional feature contract")
        audit.check(f"{arm}_scope_resolution", all(isinstance(row.get("feature_scope_index"), int) and 0 <= row["feature_scope_index"] < len(scope_rows) and scope_rows[row["feature_scope_index"]].get("episode_id") == row.get("source_episode_id") and scope_rows[row["feature_scope_index"]].get("input_sha256") for row in rows), "every primary/auxiliary feature reference resolves by index to its exact training-only source episode and input hash")

    if all(len(arm_rows.get(arm, [])) == 15_000 for arm in ARMS):
        primary_projections = [
            [(r.get("group_id"), r.get("target_hash"), r.get("candidate_semantic_ids"), r.get("candidate_mask"), r.get("loss_weight")) for r in arm_rows[arm][:10_000]]
            for arm in ARMS
        ]
        aux_common = [
            [(r.get("target_hash"), r.get("target"), r.get("candidate_semantic_ids"), r.get("candidate_mask"), r.get("loss_weight"), r.get("batch_slot"), r.get("target_source_episode_id")) for r in arm_rows[arm][10_000:]]
            for arm in ARMS
        ]
        audit.check("cross_arm_primary_equality", primary_projections[0] == primary_projections[1] == primary_projections[2], "all three arms have identical primary IDs/targets/schema/masks/weights")
        audit.check("cross_arm_aux_target_schedule_equality", aux_common[0] == aux_common[1] == aux_common[2], "all three arms have identical auxiliary targets, anchor slots, schema, and weights")
        source_lists = [[r.get("source_episode_id") for r in arm_rows[arm][10_000:]] for arm in ARMS]
        audit.check("cross_arm_aux_source_differs", source_lists[0] != source_lists[1] and source_lists[1] != source_lists[2] and source_lists[0] != source_lists[2], "the auxiliary source pointer is the only arm-specific payload")

    surface_summary: dict[str, Any] = {}
    for arm in ("B-MATCHED", "B-SHAM"):
        counts: dict[str, Any] = {
            "pairs": 0,
            "same_character_length": 0,
            "same_whitespace_token_count": 0,
            "one_changed_line": 0,
            "one_changed_character": 0,
            "changed_fields": {},
            "whitespace_tokens_before_changed_field": {},
            "changed_line_numbers_one_based": {},
        }
        rows = arm_rows.get(arm, [])
        if len(rows) == 15_000 and len(scope_rows) == 55_000:
            for aux in rows[10_000:]:
                anchor = scope_by_episode.get(aux.get("target_source_episode_id"))
                source_index = aux.get("feature_scope_index")
                source = scope_rows[source_index] if isinstance(source_index, int) and 0 <= source_index < len(scope_rows) else None
                if anchor is None or source is None or source.get("episode_id") != aux.get("source_episode_id"):
                    continue
                pair = surface_pair(anchor, source)
                counts["pairs"] += 1
                for key in ("same_character_length", "same_whitespace_token_count", "one_changed_line", "one_changed_character"):
                    counts[key] += int(pair[key])
                if pair["changed_field"] is not None:
                    field = pair["changed_field"]
                    counts["changed_fields"][field] = counts["changed_fields"].get(field, 0) + 1
                    offset = pair["whitespace_tokens_before_changed_field"]
                    counts["whitespace_tokens_before_changed_field"][field] = offset
                if pair["changed_line_number"] is not None:
                    line = str(pair["changed_line_number"])
                    counts["changed_line_numbers_one_based"][line] = counts["changed_line_numbers_one_based"].get(line, 0) + 1
        surface_summary[arm] = counts
    declared_surface = run["head_input_and_architecture"].get("training_surface_audit", {})
    surface_ok = (
        surface_summary.get("B-MATCHED", {}).get("pairs") == 5_000
        and surface_summary["B-MATCHED"].get("same_character_length") == 5_000
        and surface_summary["B-MATCHED"].get("same_whitespace_token_count") == 5_000
        and surface_summary["B-MATCHED"].get("one_changed_line") == 5_000
        and surface_summary["B-MATCHED"].get("one_changed_character") == 5_000
        and surface_summary["B-MATCHED"].get("changed_fields") == {"Neutral axis 4": 566, "Neutral axis 5": 4_434}
        and surface_summary["B-MATCHED"].get("whitespace_tokens_before_changed_field") == {"Neutral axis 4": 25, "Neutral axis 5": 30}
        and surface_summary["B-MATCHED"].get("changed_line_numbers_one_based") == {"7": 566, "8": 4_434}
        and surface_summary.get("B-SHAM", {}).get("pairs") == 5_000
        and surface_summary["B-SHAM"].get("same_character_length") == 5_000
        and surface_summary["B-SHAM"].get("same_whitespace_token_count") == 5_000
        and surface_summary["B-SHAM"].get("one_changed_line") == 5_000
        and surface_summary["B-SHAM"].get("one_changed_character") == 5_000
        and surface_summary["B-SHAM"].get("changed_fields") == {"Independent panel marker": 5_000}
        and surface_summary["B-SHAM"].get("whitespace_tokens_before_changed_field") == {"Independent panel marker": 10}
        and surface_summary["B-SHAM"].get("changed_line_numbers_one_based") == {"3": 5_000}
        and declared_surface.get("status") == "PASS_EDIT_MAGNITUDE_AND_SERIALIZATION; EDIT_LOCATION_AND_FIELD_IDENTITY_DIFFER_BY_TREATMENT"
        and declared_surface.get("matched_neutral", {}).get("changed_field_distribution") == surface_summary["B-MATCHED"]["changed_fields"]
        and declared_surface.get("matched_neutral", {}).get("whitespace_tokens_before_edited_field") == surface_summary["B-MATCHED"]["whitespace_tokens_before_changed_field"]
        and declared_surface.get("matched_neutral", {}).get("changed_line_numbers_one_based") == surface_summary["B-MATCHED"]["changed_line_numbers_one_based"]
        and declared_surface.get("certified_sham", {}).get("changed_field_distribution") == surface_summary["B-SHAM"]["changed_fields"]
        and declared_surface.get("certified_sham", {}).get("whitespace_tokens_before_edited_field") == surface_summary["B-SHAM"]["whitespace_tokens_before_changed_field"]
        and declared_surface.get("certified_sham", {}).get("changed_line_numbers_one_based") == surface_summary["B-SHAM"]["changed_line_numbers_one_based"]
    )
    audit.check("training_surface_extraction_audit", surface_ok, "all 5000 training matched and sham pairs have equal serialized length/token count and one-character edits; distinct field identities and line positions are explicitly retained as residual treatment differences")

    schedule = read_jsonl(schedule_path)
    expected_keys = {(seed, epoch, step) for seed in SEEDS for epoch in (1, 2, 3) for step in range(1, 41)}
    observed_keys = {(row.get("seed"), row.get("epoch"), row.get("step")) for row in schedule}
    audit.check("schedule_cardinality", len(schedule) == 360 and observed_keys == expected_keys, "exactly 40 steps for each of 3 epochs and 3 seeds")
    schedule_ok = True
    for seed in SEEDS:
        for epoch in (1, 2, 3):
            rows = sorted((r for r in schedule if r["seed"] == seed and r["epoch"] == epoch), key=lambda r: r["step"])
            expected_order = sorted(range(len(primary)), key=lambda i: primary[i]["group_id"])
            random.Random(seed + epoch - 1).shuffle(expected_order)
            got_order = [index for row in rows for index in row["primary_occurrence_indices"]]
            if got_order != expected_order:
                schedule_ok = False
            seen_aux: list[int] = []
            for row in rows:
                indices = row["primary_occurrence_indices"]
                expected_slots = [index // 2 for index in indices if index % 2 == 0]
                slots = row["auxiliary_anchor_batch_slots"]
                if slots != expected_slots or row.get("active_auxiliary_count") != len(expected_slots):
                    schedule_ok = False
                seen_aux.extend(slots)
                if len(indices) > 256:
                    schedule_ok = False
            if len(got_order) != 10_000 or sorted(seen_aux) != list(range(5_000)):
                schedule_ok = False
            if [len(row["primary_occurrence_indices"]) for row in rows][-1] != 16:
                schedule_ok = False
    audit.check("schedule_reconstruction", schedule_ok, "frozen Python shuffle rule reconstructs exact primary order; auxiliary slots equal anchor occurrence indices / 2 in-order and occur once per anchor per epoch")
    audit.check("schedule_aux_reuse_semantics", run["training"]["auxiliary_per_epoch"]["distinct_slots"] == 5_000 and "15000 auxiliary loss-event exposures" in run["training"]["auxiliary_per_epoch"]["reuse_across_epochs"], "5000 sealed auxiliary source rows are reused once per epoch for 15000 total event exposures")

    panel_contract = analysis["evaluation_surface"]
    final_panel = final["heldout_matched_neutral_panel"]
    audit.check("heldout_panel_identity", panel_contract.get("identity") == "v0.8N-eval-panel-v01/matched-panel-v02" and final_panel.get("identity") == "v0.8N-eval-panel-v01" and panel_contract.get("seal_manifest_sha256") == final_panel.get("seal_sha256") == EXPECTED["heldout_seal"] and panel_contract.get("panel_hash_tree_sha256") == final_panel.get("hash_tree_sha256") == EXPECTED["heldout_tree"], "analysis points only to the sealed matched-panel-v02 under the v0.8N evaluation identity")
    audit.check("heldout_panel_shape", panel_contract.get("neighborhoods") == 2_000 and panel_contract.get("families") == {family: 500 for family in FAMILIES} and panel_contract.get("views_per_neighborhood") == ["anchor", "fact_flip", "sham", "matched_neutral"], "sealed panel contract has 2000 neighborhoods, 500 per family, with all four paired views")
    audit.check("heldout_radius_diagnostics", abs(panel_contract["heldout_matched_radius_gate"]["mean_relative_error"] - final_panel["mean_relative_radius_difference"]) < 1e-15 and abs(panel_contract["heldout_matched_radius_gate"]["p95_absolute_error"] - final_panel["p95_absolute_radius_difference"]) < 1e-15 and panel_contract["heldout_selected_axis_counts"] == final_panel["semantic_axis_composition"], "analysis-side geometry metadata matches the sealed outcome-blind panel receipt")
    audit.check("heldout_firewall", firewall.get("status") == "V08N_HELDOUT_PANEL_FIREWALL_LOCKED" and firewall.get("body_access_granted") is False and firewall.get("training_process_may_read_panel") is False and firewall.get("evaluation_process_may_read_panel") is False and firewall.get("unlock_requires_explicit_phase_b_authorization") is True and firewall.get("newtight_access") is False and firewall.get("legacy_evaluation_access") is False and firewall.get("phoenix_access") is False, "firewall metadata confirms held-out bodies are dark until separate explicit authorization")
    audit.check("panel_seal_metadata", panel_seal.get("panel_locked") is True and panel_seal.get("phase_b_authorized") is False and panel_seal.get("hash_tree_sha256") == EXPECTED["heldout_tree"] and panel_validation.get("status") == "PASS", "seal/validation metadata pass without reading held-out panel content")
    audit.check("analysis_not_broadened", analysis["reporting"].get("newtight") is False and analysis["reporting"].get("legacy_panels") is False and analysis["boundaries"].get("newtight_access") is False and analysis["boundaries"].get("phoenix_access") is False and analysis["evaluation_surface"].get("other_evaluation_surfaces") == [], "NewTight, legacy evaluation, and Phoenix remain excluded")
    audit.check("analysis_sensitivity_rules", analysis["sensitivity_guard_and_claim_rules"]["absolute_sensitivity_floor"]["minimum_per_seed"] == 0.37 and analysis["sensitivity_guard_and_claim_rules"]["absolute_sensitivity_floor"]["applies_to_arms"] == ["B-MATCHED", "B-SHAM"] and analysis["sensitivity_guard_and_claim_rules"]["maximum_mean_loss_vs_matched"] == 0.05, "absolute 0.37 per-seed floor and inherited 5pp relative guard are frozen")
    k_summary = read_json(K_SUMMARY)
    k_rates = [row["K-DUP"]["strict_transition"] for row in k_summary["terminal_by_seed"]]
    audit.check("sensitivity_floor_source", k_summary.get("status") == "COMPLETE" and min(k_rates) == 0.37 and analysis["sensitivity_guard_and_claim_rules"]["absolute_sensitivity_floor"]["historical_source_sha256"] == EXPECTED["k_summary"], "0.37 floor equals the lowest terminal K-DUP seed in the sealed historical report")

    audit.check("pretraining_and_eval_boundary", run["evaluation_gate"]["training_process_filesystem_scope"]["not_readable"] and run["evaluation_gate"]["then_unlock_once"] == "v0.8N-eval-panel-v01 matched-panel-v02 only" and analysis["boundaries"]["panel_open_before_training_seal"] is False, "training process cannot access protected panels; evaluation opens once after complete terminal checkpoint seal")
    audit.check("run_output_absent", not output_root.exists(), "Phase-B run output identity has not been created before authorization")
    audit.check("candidate_tensor_not_yet_materialized", exec_receipt["candidate_catalog"].get("feature_tensor_materialized") is False and exec_receipt["candidate_catalog"].get("feature_tensor_required_after_phase_b_authorization") is True, "candidate features remain unextracted and are deferred until explicit authorization")

    if audit.failures:
        return audit, {}

    contracts = {
        "run": {"path": str(run_path.resolve()), "sha256": run_sha},
        "analysis": {"path": str(analysis_path.resolve()), "sha256": analysis_sha},
    }
    sources = {
        "final_v09_sha256": EXPECTED["final_v09"],
        "phase_b_v02_sha256": EXPECTED["phase_b_v02"],
        "execution_input_receipt_sha256": EXPECTED["execution_receipt"],
        "execution_input_hash_tree_sha256": EXPECTED["execution_tree"],
        "preflight_v02_sha256": EXPECTED["preflight"],
        "candidate_input_manifest_sha256": EXPECTED["candidate_text"],
        "heldout_panel_seal_sha256": EXPECTED["heldout_seal"],
        "heldout_panel_tree_sha256": EXPECTED["heldout_tree"],
        "heldout_firewall_sha256": EXPECTED["firewall"],
    }
    details = {
        "training": {
            "seeds": list(SEEDS),
            "arms": list(ARMS),
            "runs": 9,
            "epoch_checkpoints": 27,
            "optimizer_steps_per_arm_seed": 120,
            "primary_occurrences_per_epoch": 10_000,
            "auxiliary_event_exposures_per_epoch": 5_000,
            "auxiliary_event_exposures_per_run": 15_000,
            "candidate_tensor": "not materialized; first post-authorization model contact",
        },
        "analysis": {
            "primary": "B-SHAM versus B-MATCHED on terminal held-out sham locality",
            "secondary": "matched-vs-duplicate, cross-perturbation interaction, FACT sensitivity, anchor preservation",
            "heldout_neighborhoods": 2_000,
            "sensitivity_floor_per_seed": 0.37,
            "newtight": False,
        },
        "surface_audit": surface_summary,
    }
    return audit, {"contracts": contracts, "sources": sources, "details": details}


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def seal_packet(audit: Audit, verified: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    output_names = (
        "phase-b-run-contract-v01.json",
        "phase-b-analysis-contract-v01.json",
        "authorization-candidate-receipt.json",
        "packet-hash-tree.json",
    )
    for name in output_names:
        if (PACKET / name).exists():
            raise FileExistsError(f"refusing to overwrite existing sealed packet artifact: {PACKET / name}")

    source_run = PHASE_B / "phase-b-run-contract-v01.json"
    source_analysis = PHASE_B / "phase-b-analysis-contract-v01.json"
    copy_specs = (
        (source_run, PACKET / output_names[0]),
        (source_analysis, PACKET / output_names[1]),
    )
    for source, destination in copy_specs:
        write_new(destination, source.read_bytes())

    receipt = {
        "protocol": "jev-information-density/v0.8n-phase-b-authorization-candidate/v01",
        "identity": "v0.8N-phase-b-authorization-candidate-v01",
        "status": "V08N_PHASE_B_AUTHORIZATION_CANDIDATE_SEALED_NOT_AUTHORIZED",
        "phase_b_ready": True,
        "phase_b_authorized": False,
        "authorization_event": None,
        "authorized_actions": [],
        "construction_status": "final-v09 sealed; unchanged upstream construction and preflight receipts verified",
        "local_read_only_audit": {
            "status": "PASS",
            "method": "main-agent read-only reconstruction against sealed contracts/manifests; not a second-person review; no LFM load, candidate tensor materialization, held-out body access, inference, training, NewTight, or Phoenix",
            "check_count": len(audit.checks),
            "failed_checks": 0,
            "checks": audit.checks,
        },
        "independent_review": review,
        "contracts": verified["contracts"],
        "source_identities": verified["sources"],
        "run_analysis_summary": verified["details"],
        "boundaries": {
            "candidate_feature_extraction": "first model-contact action only after a separate explicit Phase-B authorization",
            "heldout_panel": "sealed and firewalled; unopened",
            "newtight": "not authorized or included",
            "phoenix": "not contacted",
            "model_loaded": False,
            "head_training": False,
            "evaluation_inference": False,
        },
        "required_next_authority": "explicit user action creating a separate authorization event; this candidate receipt is not authorization",
    }
    receipt_path = PACKET / output_names[2]
    write_new(receipt_path, (json.dumps(receipt, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))

    entries = []
    paths = [
        PACKET / output_names[0],
        PACKET / output_names[1],
        PACKET / "candidate-model-input-manifest.jsonl",
        receipt_path,
        Path(__file__),
    ]
    for name, item in sorted(audit.files.items()):
        path = Path(item["path"])
        if path == Path(__file__).resolve():
            continue
        if path not in paths:
            paths.append(path)
    for path in paths:
        entries.append({"path": str(path.resolve()), "sha256": sha256_file(path), "size_bytes": path.stat().st_size})
    tree = {
        "protocol": "jev-information-density/v0.8n-phase-b-authorization-packet-hash-tree/v01",
        "identity": "v0.8N-phase-b-authorization-candidate-v01",
        "status": "SEALED_CANDIDATE_NOT_AUTHORIZED",
        "entries": entries,
        "heldout_content_policy": "panel body and feature files were not opened; only existing seal/firewall metadata receipts were verified",
    }
    tree_path = PACKET / output_names[3]
    write_new(tree_path, (json.dumps(tree, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return {"receipt_path": str(receipt_path), "hash_tree_path": str(tree_path), "entries": len(entries)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seal-packet", action="store_true", help="write immutable contract copies, candidate receipt, and detached hash tree")
    parser.add_argument("--reviewer-id", help="independent reviewer identity recorded in the candidate receipt")
    parser.add_argument("--review-disposition", choices=("PASS", "FAIL", "LUNA_NO_ARTIFACT"), help="hash-specific independent review result or explicit no-artifact disposition")
    parser.add_argument("--reviewed-run-sha256", help="run-contract hash explicitly checked by the reviewer")
    parser.add_argument("--reviewed-analysis-sha256", help="analysis-contract hash explicitly checked by the reviewer")
    parser.add_argument("--local-fallback", action="store_true", help="record the bounded no-artifact review and use the passing local audit fallback")
    args = parser.parse_args()
    audit, verified = verify()
    result: dict[str, Any] = {
        "status": "PASS" if not audit.failures else "FAIL",
        "checks": audit.checks,
        "failure_count": len(audit.failures),
        "failures": audit.failures,
        "verified": verified,
        "packet_sealed": False,
        "model_loaded": False,
        "heldout_content_opened": False,
        "head_training": False,
        "evaluation_inference": False,
        "newtight_access": False,
        "phoenix_access": False,
    }
    if not audit.failures and args.seal_packet:
        review = {
            "reviewer_id": args.reviewer_id,
            "disposition": args.review_disposition,
            "reviewed_run_contract_sha256": args.reviewed_run_sha256,
            "reviewed_analysis_contract_sha256": args.reviewed_analysis_sha256,
            "separate_artifact_produced": False,
            "bounded_wait_calls": 3 if args.review_disposition == "LUNA_NO_ARTIFACT" else None,
            "local_fallback_used": args.local_fallback,
            "record_source": "bounded reviewer wait returned no final output; no separate reviewer artifact" if args.review_disposition == "LUNA_NO_ARTIFACT" else "hash-specific subagent final message; no separate reviewer artifact",
        }
        exact_contract_hashes = (
            args.reviewed_run_sha256 == verified["contracts"]["run"]["sha256"]
            and args.reviewed_analysis_sha256 == verified["contracts"]["analysis"]["sha256"]
        )
        review_complete = bool(args.reviewer_id) and (
            (args.review_disposition == "PASS" and exact_contract_hashes and not args.local_fallback)
            or (args.review_disposition == "LUNA_NO_ARTIFACT" and args.local_fallback and not args.reviewed_run_sha256 and not args.reviewed_analysis_sha256)
        )
        if not review_complete:
            result["status"] = "PASS_LOCAL_AUDIT_REVIEW_GATE_CLOSED"
            result["failures"] = ["candidate packet sealing requires a PASS review bound to the exact current run and analysis contract hashes"]
            result["failure_count"] = 1
        else:
            result["sealed_artifacts"] = seal_packet(audit, verified, review)
            result["packet_sealed"] = True
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not audit.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
