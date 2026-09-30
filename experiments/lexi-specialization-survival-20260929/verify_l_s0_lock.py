"""Verify the frozen Rung-0 ruler and graph-local Rung-1 sentinel."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def verify(root: Path, lock_path: Path) -> list[str]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("schema") != "phoenix.lexi-specialization-survival/l-s0-lock-v1":
        raise ValueError("unexpected L-S0 lock schema")
    if lock.get("status") != "LOCKED":
        raise ValueError("L-S0 baseline is not locked")

    rung0_path = resolve(root, lock["rung0"]["lock_path"])
    actual_rung0 = sha256(rung0_path)
    if actual_rung0 != lock["rung0"]["lock_sha256"]:
        raise ValueError(f"Rung-0 lock hash mismatch: {actual_rung0}")

    checked = [str(rung0_path)]
    for item in lock["artifacts"]:
        path = resolve(root, item["path"])
        actual = sha256(path)
        if actual != item["sha256"]:
            raise ValueError(f"{item['role']} hash mismatch: {actual}")
        checked.append(str(path))

    results = json.loads(Path(lock["artifacts"][4]["path"]).read_text(encoding="utf-8"))
    gate = results["gate"]
    if gate["status"] != "PASS" or gate["passing_tasks"] != ["edge_existence"]:
        raise ValueError("Rung-1 edge-existence sentinel no longer matches the locked gate result")
    summary = results["task_summary"]["edge_existence"]
    sentinel = lock["graph_rung1_sentinel"]
    observed = {
        "test_auc": summary["test_metric"],
        "held_renderer_s7_s8_s9_auc": summary["held_renderer_metric"],
        "held_control_auc": summary["held_renderer_control_metric"],
        "held_advantage": summary["held_renderer_margin_over_control"],
        "in_family_auc": summary["in_family_metric"],
        "renderer_drop": summary["renderer_drop"],
    }
    if observed != {key: sentinel[key] for key in observed}:
        raise ValueError(f"Rung-1 sentinel score mismatch: {observed}")

    base_weights = resolve(root, lock["backbone"]["revision_path"] + "/model.safetensors")
    if sha256(base_weights) != lock["backbone"]["weights_sha256"]:
        raise ValueError("pinned base-model weights changed")
    checked.append(str(base_weights))

    rung0_verifier = root / "experiments/bank-v1-rung0-atlas-20260929/verify_rung0_lock.py"
    subprocess.run([sys.executable, str(rung0_verifier)], cwd=root, check=True)
    return checked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path,
                        default=Path(__file__).resolve().parents[2])
    parser.add_argument("--lock", type=Path, default=Path(__file__).with_name("L-S0-lock.json"))
    args = parser.parse_args()
    checked = verify(args.repo_root.resolve(), args.lock.resolve())
    print(json.dumps({"status": "L_S0_VERIFIED", "checked_files": len(checked),
                      "lock": str(args.lock.resolve())}, sort_keys=True))


if __name__ == "__main__":
    main()
