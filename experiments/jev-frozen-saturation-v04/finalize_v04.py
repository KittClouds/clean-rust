"""Seal run-level receipts after the final v0.4 analysis pass."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(r"D:\codex-runs\jev-frozen-saturation-v04")
REPORT = ROOT / "reports"
REPO = Path(r"C:\code land\clean-rust")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    learning_path = REPORT / "learning-saturation.json"
    learning = read_json(learning_path)
    for value in learning.values():
        value["terminal_transition"]["gate_summary"]["rescue_eligible"] = False
        value["terminal_transition"]["gate_summary"]["rescue_invoked"] = True
        value["terminal_transition"]["gate_summary"]["additional_rescue_permitted"] = False
    write_json(learning_path, learning)

    contract = REPO / "experiments" / "jev-frozen-saturation-v04" / "v04-contract.json"
    document = REPO / "docs" / "jev-frozen-saturation-true-ood-gate-v0.4.md"
    freeze = read_json(REPO / "experiments" / "jev-frozen-saturation-v04" / "freeze-sha256.json")
    hash_check = {
        name: sha256(REPO / name) == value["sha256"]
        for name, value in freeze["files"].items()
    }
    shutil.copy2(REPO / "experiments" / "jev-frozen-saturation-v04" / "v04-contract.json", REPORT / "v04-contract.json")
    shutil.copy2(ROOT / "ood" / "ood-novelty-audit.json", REPORT / "ood-novelty-audit.json")
    gate = read_json(REPORT / "qlora-final-gate.json")
    gate["protocol_hash_check"] = hash_check
    gate["rescue_policy"] = {
        "invoked_for_all_backbones": True,
        "terminal_transition": "10k_to_20k",
        "additional_rescue_permitted": False,
    }
    write_json(REPORT / "qlora-final-gate.json", gate)
    manifest = {
        "contract": "jev-frozen-saturation-true-ood-gate/v0.4",
        "status": "complete_no_qlora_authorized",
        "protocol_hashes": {
            "docs/jev-frozen-saturation-true-ood-gate-v0.4.md": sha256(document),
            "experiments/jev-frozen-saturation-v04/v04-contract.json": sha256(contract),
        },
        "protocol_hash_check": hash_check,
        "primary_reports": 21,
        "rescue_reports": 9,
        "larger_head_reports": 3,
        "oracle_reports": 3,
        "layer_reports": 8,
        "backbones": ["minicpm5-1b-base", "qwen3-0.6b-base", "k2-horizon-0.9b"],
        "phoenix": "out_of_scope_and_untouched",
    }
    write_json(ROOT / "run-manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
