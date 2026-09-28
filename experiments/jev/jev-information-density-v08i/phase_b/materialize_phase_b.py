"""Build the authorized held-out contrast view without changing Phase-A banks."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import preflight_phase_b as preflight


ROOT = Path(__file__).resolve().parents[3]
PHASE_B = Path(__file__).resolve().parent
CONTRACT = PHASE_B / "phase-b-v01-contract.json"
RUN = Path(r"D:\codex-runs\jev-information-density-v08i\phase-b-v01")
PHASE_A = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean")
MATERIALIZED = PHASE_A / "materialized"
INPUTS = RUN / "inputs"
PROFILE = "name_definition"


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import frozen Phase-A helper {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            encoded = line.encode("utf-8")
            stream.write(line)
            digest.update(encoded)
    return digest.hexdigest()


def read_indexed_texts(path: Path) -> list[str]:
    result = []
    for expected, row in enumerate(read_jsonl(path)):
        if row.get("index") != expected or not isinstance(row.get("text"), str):
            raise ValueError(f"invalid indexed text table {path}, row {expected}")
        result.append(row["text"])
    return result


def find_candidate_id(semantic_ids: list[str], suffix: str) -> str:
    matches = [value for value in semantic_ids if value.endswith("::" + suffix)]
    if len(matches) != 1:
        raise ValueError(f"expected one candidate semantic ID ending in {suffix!r}, got {matches}")
    return matches[0]


def main() -> int:
    contract = preflight.read_json(CONTRACT)
    auth_path = RUN / "preflight/model-contact-authorization.json"
    auth = preflight.read_json(auth_path)
    if auth.get("status") != "PASS" or auth.get("model_contact_authorized") is not True:
        raise RuntimeError("Phase-B preflight did not authorize the run")
    if auth.get("contract_sha256") != preflight.sha256_file(CONTRACT):
        raise RuntimeError("Phase-B contract changed after preflight")
    for arm in ("S100", "F100"):
        bank_path = MATERIALIZED / f"{arm}-groups.jsonl"
        expected = contract["phase_a_seal"][f"{arm}_sha256"]
        if preflight.sha256_file(bank_path) != expected:
            raise RuntimeError(f"sealed Phase-A {arm} bank changed before materialization")
    for name, key in (("eval-canonical-episodes.jsonl", "heldout_canonical_episodes_sha256"),
                      ("eval-contrast-certificates.jsonl", "heldout_contrast_certificates_sha256")):
        if preflight.sha256_file(PHASE_A / name) != contract["phase_a_seal"][key]:
            raise RuntimeError(f"sealed Phase-A held-out source changed before materialization: {name}")
    if INPUTS.exists():
        raise FileExistsError(f"Phase-B inputs already exist; preserve and investigate: {INPUTS}")
    INPUTS.mkdir()

    helper = load_module("jev_phase_a_assembler_v02", ROOT / "experiments/jev-information-density-v08i/assemble_phase_a.py")
    state_texts = read_indexed_texts(MATERIALIZED / "state-inputs.jsonl")
    candidate_texts = read_indexed_texts(MATERIALIZED / "candidate-inputs-name_definition.jsonl")
    state_lookup = {text: index for index, text in enumerate(state_texts)}
    candidate_lookup = {text: index for index, text in enumerate(candidate_texts)}

    cert_path = PHASE_A / "eval-contrast-certificates.jsonl"
    episode_path = PHASE_A / "eval-canonical-episodes.jsonl"
    certificates = read_jsonl(cert_path)
    wanted: dict[str, tuple[dict[str, Any], str]] = {}
    for certificate in certificates:
        for role, episode_id in certificate["episode_ids"].items():
            if episode_id in wanted:
                raise ValueError(f"duplicate held-out episode identity: {episode_id}")
            wanted[episode_id] = (certificate, role)

    found: dict[str, dict[str, Any]] = {}
    for episode in read_jsonl(episode_path):
        episode_id = str(episode.get("episode_id", ""))
        if episode_id in wanted:
            if episode_id in found:
                raise ValueError(f"duplicate canonical held-out episode: {episode_id}")
            found[episode_id] = episode
    if set(found) != set(wanted):
        raise ValueError(f"held-out canonical coverage mismatch: found={len(found)}, expected={len(wanted)}")

    contrast_rows: list[dict[str, Any]] = []
    family_counts: Counter[str] = Counter()
    for certificate in certificates:
        anchor_id = str(certificate["anchor_id"])
        triplet = {
            role: found[str(certificate["episode_ids"][role])]
            for role in ("anchor", "fact_flip", "sham")
        }
        helper.validate_triplet(certificate, {(anchor_id, role): episode for role, episode in triplet.items()})
        family = str(certificate["world_family_id"])
        family_counts[family] += 1
        old_winner = find_candidate_id(
            [item["candidate_semantic_id"] for item in triplet["anchor"]["runtime_schema"]["candidates"]],
            str(certificate["expected_label_before"]),
        )
        new_winner = find_candidate_id(
            [item["candidate_semantic_id"] for item in triplet["anchor"]["runtime_schema"]["candidates"]],
            str(certificate["expected_label_after"]),
        )
        for role in ("anchor", "fact_flip", "sham"):
            episode = triplet[role]
            row = helper.group_from_episode(episode, "eval", f"phaseb-eval-root:{anchor_id}")
            row["contrast_anchor_id"] = anchor_id
            row["contrast_role"] = role
            row["contrast_family_id"] = family
            row["expected_old_winner_id"] = old_winner
            row["expected_new_winner_id"] = new_winner
            state_text = row.pop("_state_text")
            state_index = state_lookup.get(state_text)
            if state_index is None:
                state_index = len(state_texts)
                state_texts.append(state_text)
                state_lookup[state_text] = state_index
            row["state_idx"] = state_index
            surfaces = row.pop("_candidate_surfaces")[PROFILE]
            indices = []
            for surface in surfaces:
                candidate_index = candidate_lookup.get(surface)
                if candidate_index is None:
                    candidate_index = len(candidate_texts)
                    candidate_texts.append(surface)
                    candidate_lookup[surface] = candidate_index
                indices.append(candidate_index)
            row["candidate_indices"] = {PROFILE: indices}
            contrast_rows.append(row)

    if len(certificates) != 2_000 or len(contrast_rows) != 6_000:
        raise ValueError("held-out contrast dose drifted")
    if len(family_counts) != 4 or any(count != 500 for count in family_counts.values()):
        raise ValueError(f"held-out family balance drifted: {dict(family_counts)}")

    train_s = read_jsonl(MATERIALIZED / "S100-groups.jsonl")
    train_f = read_jsonl(MATERIALIZED / "F100-groups.jsonl")
    for arm, groups in (("S100", train_s), ("F100", train_f)):
        if len(groups) != 100_000 or len({row["group_id"] for row in groups}) != 100_000:
            raise ValueError(f"{arm} group count/uniqueness changed")
        if any(row.get("split") != "train" for row in groups):
            raise ValueError(f"{arm} contains a non-training row")
        if any(row.get("open_world") or row.get("kind") not in {"choice", "independent"} for row in groups):
            raise ValueError(f"{arm} contains a target unsupported by the frozen head")
        for row in groups:
            if not 0 <= int(row["state_idx"]) < len(state_texts):
                raise ValueError(f"{arm} state index out of range: {row['group_id']}")
            indices = row["candidate_indices"][PROFILE]
            if len(indices) != len(row["candidate_semantic_ids"]) or len(indices) != len(row["gold"]):
                raise ValueError(f"{arm} candidate alignment mismatch: {row['group_id']}")
            if any(not 0 <= int(index) < len(candidate_texts) for index in indices):
                raise ValueError(f"{arm} candidate index out of range: {row['group_id']}")

    state_sha = write_jsonl(INPUTS / "state-inputs.jsonl", [
        {"index": index, "text": text} for index, text in enumerate(state_texts)
    ])
    candidate_sha = write_jsonl(INPUTS / "candidate-inputs-name_definition.jsonl", [
        {"index": index, "text": text} for index, text in enumerate(candidate_texts)
    ])
    eval_sha = write_jsonl(INPUTS / "heldout-contrast-groups.jsonl", contrast_rows)
    receipt = {
        "protocol": contract["protocol"],
        "status": "PHASE_B_INPUTS_READY_NO_NEW_MODEL_LOAD",
        "contract_sha256": auth["contract_sha256"],
        "authorization_receipt_sha256": preflight.sha256_file(auth_path),
        "phase_a_identity": "phase-a-v02-clean",
        "source_bank_paths": {
            "S100": str(MATERIALIZED / "S100-groups.jsonl"),
            "F100": str(MATERIALIZED / "F100-groups.jsonl"),
        },
        "source_bank_sha256": {
            "S100": contract["phase_a_seal"]["S100_sha256"],
            "F100": contract["phase_a_seal"]["F100_sha256"],
        },
        "heldout_source_sha256": {
            "canonical_episodes": contract["phase_a_seal"]["heldout_canonical_episodes_sha256"],
            "contrast_certificates": contract["phase_a_seal"]["heldout_contrast_certificates_sha256"],
        },
        "training_occurrences_preserved": {"S100": 100_000, "F100": 100_000},
        "training_groups_copied_or_deduplicated": False,
        "heldout_pairs": len(certificates),
        "heldout_groups": len(contrast_rows),
        "heldout_family_counts": dict(sorted(family_counts.items())),
        "profile": PROFILE,
        "state_text_count": len(state_texts),
        "candidate_text_count": len(candidate_texts),
        "input_tables": {
            "state_inputs": {"path": str(INPUTS / "state-inputs.jsonl"), "sha256": state_sha},
            "candidate_inputs": {"path": str(INPUTS / "candidate-inputs-name_definition.jsonl"), "sha256": candidate_sha},
            "heldout_groups": {"path": str(INPUTS / "heldout-contrast-groups.jsonl"), "sha256": eval_sha},
        },
        "triplet_semantics_validated": True,
        "model_loaded_by_materializer": False,
        "feature_extraction": False,
        "training": False,
        "phoenix_access": False,
    }
    receipt_path = INPUTS / "phase-b-inputs-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "train_groups_per_arm": 100_000,
                      "heldout_pairs": len(certificates), "heldout_groups": len(contrast_rows),
                      "state_texts": len(state_texts), "candidate_texts": len(candidate_texts),
                      "receipt": str(receipt_path)}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
