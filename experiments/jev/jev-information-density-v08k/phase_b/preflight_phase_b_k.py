"""Fail-closed Phase-B authorization for v0.8K."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CODE = Path(__file__).resolve().parent
PHASE_A_RUN = Path(r"D:\codex-runs\jev-information-density-v08k\phase-a-v01-clean")
RUN = Path(r"D:\codex-runs\jev-information-density-v08k\phase-b-v01")
CONTRACT = CODE / "phase-b-v01-contract.json"
PHASE_A_CONTRACT = ROOT / "experiments/jev-information-density-v08k/phase_a/phase-a-v01-contract.json"
F100 = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean\materialized\F100-groups.jsonl")
J_SEAL = Path(r"D:\codex-runs\jev-information-density-v08j\seal\v08j-seal-manifest.json")
J_SHAM = Path(r"D:\codex-runs\jev-information-density-v08j\phase-a-v01\inputs\sham-views.jsonl")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    contract = read_json(CONTRACT)
    phase_a_contract = read_json(PHASE_A_CONTRACT)
    receipt = read_json(PHASE_A_RUN / "phase-a-receipt.json")
    lineage = read_json(PHASE_A_RUN / "phase-a-lineage-audit.json")
    triplet_audit = read_json(PHASE_A_RUN / "phase-a-triplet-audit.json")
    seal_manifest = read_json(PHASE_A_RUN / "seal/k-phase-a-seal-manifest.json")
    seal_audit = read_json(PHASE_A_RUN / "seal/k-phase-a-seal-audit.json")
    arm_manifests = read_json(PHASE_A_RUN / "arm-manifests.json")
    graph = read_json(PHASE_A_RUN / "objective-graph.json")

    require(contract["phase_a_identity"] == "phase-a-v01-clean", "wrong K Phase-A identity")
    require(contract["objective_graph_sha256"] == "bd574cd15bc0630ecfcc91116dda5554696313c5b3d03fd161940242f6518670", "K objective graph contract drift")
    require(contract["model"]["revision"] == "7453bca97ca1e67754c4035a4b4c584e1c9dd725", "model revision drift")
    require(phase_a_contract["lineage"]["phase_b_separate_authorization_required"] is True, "Phase-A boundary changed")
    require(receipt["status"] == "PHASE_A_READY_PHASE_B_NOT_AUTHORIZED", "K Phase-A receipt status drift")
    require(receipt["phase_a_identity"] == "phase-a-v01-clean", "K receipt identity drift")
    require(receipt["objective_graph_sha256"] == contract["objective_graph_sha256"], "K receipt graph drift")
    require(lineage["status"] == "PASS", "K lineage audit failed")
    require(lineage["forbidden_parent_used"] is False, "quarantined parentage was permitted")
    require(lineage["model_contact"] is False and lineage["feature_extraction"] is False, "Phase-A model boundary crossed")
    require("training" not in lineage and lineage["protected_eval_bodies_opened"] is False, "Phase-A execution boundary receipt malformed")
    require(lineage["Phoenix"] is False, "Phase-A Phoenix boundary crossed")
    require(triplet_audit["status"] == "PASS", "K triplet audit failed")
    require(triplet_audit["triplet_count"] == 5000, "K triplet count drift")
    require(triplet_audit["sham_gold_max_abs_error"] <= 1e-12, "K sham target tolerance failed")
    require(triplet_audit["fact_flip_map_change_count"] == 5000, "K fact-flip certificate count drift")
    require(seal_audit["status"] == "PASS" and seal_audit["mismatch_count"] == 0, "K seal audit failed")
    require(seal_manifest["status"] == "PHASE_A_COMPLETE_NONPARENTABLE_PHASE_B_UNAUTHORIZED", "K seal status drift")
    require(seal_manifest["phase_b_authorized"] is False, "K seal authorized Phase B unexpectedly")
    require(sha256_file(J_SEAL) == receipt["parent_seal_manifest_sha256"], "v0.8J parent seal drift")
    require(sha256_file(J_SHAM) == "324422fb4c5a49a715023824d9d283335b0118dc38a2542391bdb34df946f9ec", "sealed sham training source drift")
    sham_rows = read_jsonl(J_SHAM)
    require(len(sham_rows) == 5000 and all(row.get("split") == "train" for row in sham_rows), "sham training source boundary drift")
    require(graph["triplet_count"] == 5000 and graph["primary_bank"]["count"] == 100000, "K graph count drift")
    require(graph["existing_invariance_pairs"] == 4982, "inherited invariance count drift")
    require(set(graph["arms"]) == {"K-DUP", "K-SHAM"}, "K arm set drift")

    primary = read_jsonl(F100)
    require(len(primary) == 100000 and len({row["group_id"] for row in primary}) == 100000, "F100 source drift")
    require(sha256_file(F100) == receipt["primary_bank"]["sha256"], "F100 hash drift")
    triplets_path = PHASE_A_RUN / "inputs/triplets.jsonl"
    dup_path = PHASE_A_RUN / "inputs/dup-auxiliary-events.jsonl"
    sham_path = PHASE_A_RUN / "inputs/sham-auxiliary-events.jsonl"
    require(sha256_file(triplets_path) == receipt["arms"]["K-DUP"]["triplets_sha256"], "K triplets hash drift")
    require(sha256_file(dup_path) == receipt["arms"]["K-DUP"]["auxiliary_events_sha256"], "K-DUP event hash drift")
    require(sha256_file(sham_path) == receipt["arms"]["K-SHAM"]["auxiliary_events_sha256"], "K-SHAM event hash drift")
    dup = read_jsonl(dup_path)
    sham = read_jsonl(sham_path)
    require(len(dup) == 5000 and len(sham) == 5000, "K auxiliary count drift")
    require({row["auxiliary_source_role"] for row in dup} == {"anchor"}, "K-DUP source role drift")
    require({row["auxiliary_source_role"] for row in sham} == {"sham"}, "K-SHAM source role drift")
    for left, right in zip(dup, sham):
        require(left["triplet_id"] == right["triplet_id"], "K arm triplet order drift")
        require(left["target"] == right["target"] and left["loss"] == right["loss"], "K auxiliary target/loss drift")
        require(left["weight"] == right["weight"], "K auxiliary weight drift")
        require(left["batch_schedule"] == right["batch_schedule"], "K auxiliary schedule drift")
    require(arm_manifests["K-DUP"]["primary_bank_sha256"] == receipt["primary_bank"]["sha256"], "K-DUP primary hash drift")
    require(arm_manifests["K-SHAM"]["primary_bank_sha256"] == receipt["primary_bank"]["sha256"], "K-SHAM primary hash drift")

    required_code = {
        "preflight_phase_b_k.py": Path(__file__),
        "train_phase_b_k.py": CODE / "train_phase_b_k.py",
        "extract_phase_b_k_features.py": CODE / "extract_phase_b_k_features.py",
        "probe.py": ROOT / "experiments/jev-frozen-readout-v01/probe.py",
        "train_v05.py": ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py",
        "extract_lfm.py": ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py",
    }
    for name, path in required_code.items():
        require(path.is_file(), f"required Phase-B source missing: {name}")

    auth = {
        "status": "PASS",
        "protocol": contract["protocol"],
        "contract_sha256": sha256_file(CONTRACT),
        "phase_a_contract_sha256": sha256_file(PHASE_A_CONTRACT),
        "phase_a_identity": contract["phase_a_identity"],
        "objective_graph_sha256": contract["objective_graph_sha256"],
        "phase_a_seal_manifest_sha256": sha256_file(PHASE_A_RUN / "seal/k-phase-a-seal-manifest.json"),
        "parent_v08j_seal_manifest_sha256": sha256_file(J_SEAL),
        "model_contact_authorized": True,
        "feature_extraction_authorized": True,
        "training_authorized": True,
        "evaluation_bodies_opened": False,
        "phoenix_access": False,
        "verified_primary_bank_sha256": receipt["primary_bank"]["sha256"],
        "verified_triplets_sha256": receipt["arms"]["K-DUP"]["triplets_sha256"],
        "verified_dup_events_sha256": receipt["arms"]["K-DUP"]["auxiliary_events_sha256"],
        "verified_sham_events_sha256": receipt["arms"]["K-SHAM"]["auxiliary_events_sha256"],
        "verified_sham_training_source_sha256": sha256_file(J_SHAM),
        "source_code_sha256": {name: sha256_file(path) for name, path in required_code.items()},
    }
    target = RUN / "preflight/model-contact-authorization.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(auth, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(auth, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
