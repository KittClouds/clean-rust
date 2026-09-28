from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
BANKS = {
    "dev-bank-v4": {
        "frame_dir": ROOT / "tasks" / "expanded" / "dev-bank-v4",
        "markers": {
            "cyclic-palette-seam": "GradientStop::new(index as f32 / (count - 1) as f32, color)",
            "unicode-fill-boundaries": "if grapheme_aligned {",
            "unicode-pointer-selection": ".saturating_sub(0)",
            "color-interpolation-endpoints": "amount.clamp(0.01, 0.99)",
        },
    },
    "heldout-bank-v5": {
        "frame_dir": ROOT / "tasks" / "expanded" / "heldout-bank-v5",
        "markers": {
            "hard-stop-ordering": ".partition_point(|stop| stop.stop.position < position);",
            "fill-clear-intervals": "normalized.push(FillSpan { range, fill });",
            "inherited-style-preservation": "TextStyle::default().to_run(byte_len)",
            "draft-cardinality-transitions": "if stops.len() < 1 {",
        },
    },
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_excerpt(patch_path: Path) -> str:
    changed = [
        line
        for line in patch_path.read_text(encoding="utf-8").splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    if not changed:
        return "No source changes; retain the current expression."
    return "Patch lines:\n" + "\n".join(changed[:6])


def main() -> None:
    for bank_name, config in BANKS.items():
        bank_root = config["frame_dir"]
        unlocked_path = bank_root / "frames-unlocked.json"
        frame_lock_path = bank_root / "frame-lock.json"
        backup_input = bank_root / "frames-unlocked-pre-source-excerpt.json"
        backup_lock = bank_root / "frame-lock-pre-source-excerpt.json"
        if backup_input.exists() or backup_lock.exists():
            raise SystemExit(f"frame evidence amendment already recorded for {bank_name}")
        backup_input.write_bytes(unlocked_path.read_bytes())
        backup_lock.write_bytes(frame_lock_path.read_bytes())

        candidate_lock = read_json(bank_root / "candidate-lock.json")
        unlocked = read_json(unlocked_path)
        for frame in unlocked["frames"]:
            family = frame["task_family"]
            family_candidates = candidate_lock["families"][family]
            variants = family_candidates["variants"]
            variant_by_hash = {
                item["patch_sha256"]: variant
                for variant, item in variants.items()
            }
            source_id = frame["evidence"][0]["source_id"]
            prefix = "phoenix-native/crates/gpui-animated-gradient-text/"
            source_relative = source_id.removeprefix(prefix)
            base_source = ROOT / variants["keep"]["candidate_root"] / "crates" / "gpui-animated-gradient-text" / source_relative
            source_lines = base_source.read_text(encoding="utf-8").splitlines()
            marker = config["markers"][family]
            source_line = next((line.strip() for line in source_lines if marker in line), None)
            if source_line is None:
                raise SystemExit(f"source excerpt marker missing for {bank_name}/{family}: {marker}")
            frame["evidence"][0]["content"] += f"\nCurrent task-snapshot code: `{source_line}`"

            for option in frame["action_options"]:
                variant = variant_by_hash[option["patch_sha256"]]
                option["summary"] = {
                    "keep": "Retain the current implementation.",
                    "gold": "Apply the focused implementation patch.",
                    "gold_comment": "Apply the focused patch with an explanatory source comment.",
                    "mutant": "Apply the alternate implementation patch.",
                }[variant]
                patch_path = ROOT / variants[variant]["patch"]
                option["diff_excerpt"] = patch_excerpt(patch_path)

        write_json(unlocked_path, unlocked)
        env = os.environ.copy()
        env["CARGO_TARGET_DIR"] = r"D:\cargo-targets\rdc-e009"
        subprocess.run(
            [
                "cargo", "run", "--quiet", "--manifest-path", str(ROOT / "Cargo.toml"),
                "--bin", "e009-freeze-frames", "--", str(unlocked_path), str(frame_lock_path),
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )
        receipt_path = bank_root / "bank-build-receipt.json"
        receipt = read_json(receipt_path)
        receipt["frame_evidence_amendment"] = {
            "source_excerpt_added": True,
            "action_summaries_neutralized": True,
            "labels_or_completion_results_read": False,
            "pre_amendment_frame_lock_sha256": sha256(backup_lock.read_bytes()),
            "amended_frame_lock_sha256": sha256(frame_lock_path.read_bytes()),
        }
        write_json(receipt_path, receipt)
        print(f"amended {bank_name} with actual faulty source lines and neutral action descriptions")


if __name__ == "__main__":
    main()
