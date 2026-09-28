from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path


ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
OUTPUT = CONSTRUCTION / "family-design-v1.json"
SEED = 20260925

FAMILIES = [
    ("bytes", "wire-endian-contract", "task_request_dominant", ["E_c.content", "E_t"], "request_pairs"),
    ("bytes", "bounded-prefix-copy", "candidate_action_dominant", ["E_c.content"], "candidate_pairs"),
    ("bytes", "cursor-advance-observation", "pre_action_test_execution_dominant", ["E_c.content", "E_x"], "execution_pairs"),
    ("bytes", "composite-frame-field", "joint_support", ["E_c.content", "E_t", "E_x"], "xor_four_way"),
    ("clap", "repeated-option-policy", "task_request_dominant", ["E_c.content", "E_t"], "request_pairs"),
    ("clap", "possible-value-validation", "candidate_action_dominant", ["E_c.content"], "candidate_pairs"),
    ("clap", "derive-feature-compatibility", "context_sensitive", ["E_c.content", "E_r"], "context_pairs"),
    ("clap", "conflicting-alias-requirement", "abstention_positive", [], "always_abstain"),
    ("serde-json", "stream-byte-offset", "pre_action_test_execution_dominant", ["E_c.content", "E_x"], "execution_pairs"),
    ("serde-json", "number-mode-plus-error-site", "joint_support", ["E_c.content", "E_t", "E_x"], "xor_four_way"),
    ("serde-json", "map-order-feature-contract", "context_sensitive", ["E_c.content", "E_r"], "context_pairs"),
    ("serde-json", "raw-number-lossless", "abstention_positive", [], "always_abstain"),
]


def digest(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite family design: {OUTPUT}")
    rng = random.Random(SEED)
    family_codes = rng.sample(range(1000, 9999), len(FAMILIES))
    task_codes = rng.sample(range(100000, 999999), len(FAMILIES) * 4)
    rows = []
    task_ix = 0
    for family_ix, family in enumerate(FAMILIES):
        repository, family_name, stratum, support, pairing = family
        family_code = f"fam-{family_codes[family_ix]:04d}"
        tasks = []
        for within in range(4):
            task_ix += 1
            if pairing == "request_pairs":
                pair = within // 2
                switch = within % 2
                gold_role = ("action-a" if switch == 0 else "action-b")
                pair_id = f"pair-{family_codes[family_ix]:04d}-{pair + 1}"
                changed_channel = "E_t"
            elif pairing == "execution_pairs":
                pair = within // 2
                switch = within % 2
                gold_role = ("action-a" if switch == 0 else "action-b")
                pair_id = f"pair-{family_codes[family_ix]:04d}-{pair + 1}"
                changed_channel = "E_x"
            elif pairing == "context_pairs":
                pair = within // 2
                switch = within % 2
                gold_role = ("action-a" if switch == 0 else "action-b")
                pair_id = f"pair-{family_codes[family_ix]:04d}-{pair + 1}"
                changed_channel = "E_r"
            elif pairing == "candidate_pairs":
                pair = within // 2
                switch = within % 2
                gold_role = ("action-a" if switch == 0 else "action-b")
                pair_id = f"pair-{family_codes[family_ix]:04d}-{pair + 1}"
                changed_channel = "E_c.content"
            elif pairing == "xor_four_way":
                request_bit = (within >> 1) & 1
                execution_bit = within & 1
                role_index = (request_bit << 1) | execution_bit
                gold_role = ("action-a", "action-b", "action-c", "action-d")[role_index]
                pair_id = f"factorial-{family_codes[family_ix]:04d}"
                changed_channel = "E_t+E_x"
            else:
                gold_role = None
                pair_id = f"abstain-{family_codes[family_ix]:04d}"
                changed_channel = "none"
            tasks.append(
                {
                    "task_id": f"task-{task_codes[task_ix - 1]:06d}",
                    "pair_id": pair_id,
                    "within_family_index": within + 1,
                    "truth_support": support,
                    "pairing_design": pairing,
                    "counterfactual_change_channel": changed_channel,
                    "latent_gold_candidate_role": gold_role,
                    "latent_request_bit": ((within >> 1) & 1) if pairing == "xor_four_way" else None,
                    "latent_execution_bit": (within & 1) if pairing == "xor_four_way" else None,
                    "full_frame_direct_decision": "ABSTAIN" if pairing == "always_abstain" else "ACT",
                }
            )
        rows.append(
            {
                "repository_id": repository,
                "hidden_family_name": family_name,
                "observer_family_code": family_code,
                "stratum": stratum,
                "truth_support": support,
                "pairing_design": pairing,
                "tasks": tasks,
            }
        )
    rng.shuffle(rows)
    for row in rows:
        rng.shuffle(row["tasks"])
    design = {
        "schema_version": 1,
        "program": "Selective Cognition / Action Region Program",
        "experiment": "E012 Prospective Frame Decomposition",
        "state": "PRETASK_FAMILY_DESIGN",
        "model_contact_authorized": False,
        "seed": SEED,
        "task_count": len(FAMILIES) * 4,
        "family_count": len(FAMILIES),
        "sha256_self_excluded": True,
        "families": rows,
    }
    OUTPUT.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")
    print(f"design_sha256={digest(design)}")


if __name__ == "__main__":
    main()
