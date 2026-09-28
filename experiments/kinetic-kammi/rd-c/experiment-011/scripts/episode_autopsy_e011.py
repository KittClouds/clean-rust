from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011")
RUN = ROOT / "artifacts/runs/e011-20260925-causal-evidence-01"
CONDITIONS = (
    "evidence-masked",
    "evidence-swapped",
    "repository-neutralized",
    "candidate-permuted",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compiled_view(record: dict, frame: dict, labels: dict) -> dict:
    output = record.get("normalized_output")
    if not isinstance(output, dict):
        return {"patch": None, "summary": None, "accepted": False, "correct": False, "reason": "invalid-output"}
    choice = output.get("action_choice")
    selected = next(
        (option for option in frame["action_options"] if type(choice) is int and option["action"]["id"] == choice),
        None,
    )
    patch = selected["patch_sha256"] if selected else None
    app = output.get("applicability_milli")
    abst = output.get("abstention_milli")
    accepted = (
        selected is not None
        and type(app) is int and app >= 850
        and type(abst) is int and abst <= 150
    )
    return {
        "patch": patch,
        "summary": selected["summary"] if selected else None,
        "displayed_id": choice,
        "position": next((index + 1 for index, option in enumerate(frame["action_options"]) if selected and option["patch_sha256"] == patch), None),
        "applicability_milli": app,
        "abstention_milli": abst,
        "accepted": accepted,
        "correct": bool(accepted and patch and labels["actions_by_patch_sha256"].get(patch, {}).get("expected_task_completion", False)),
        "raw_correct": bool(patch and labels["actions_by_patch_sha256"].get(patch, {}).get("expected_task_completion", False)),
        "reason": "accepted" if accepted else ("explicit-abstention" if choice is None else "threshold-or-invalid"),
    }


def main() -> None:
    source = read_json(ROOT / "inputs/e010-heldout-frame-lock.json")
    labels = read_json(ROOT / "inputs/e010-heldout-sealed-labels.json")["tasks"]
    frames = {entry["frame"]["task_id"]: entry["frame"] for entry in source["frames"]}
    auxiliary = read_json(RUN / "transform-auxiliary-lock.json")
    changed_rows = []
    for task_id, base_frame in frames.items():
        repo = base_frame["repository_id"]
        family = base_frame["task_family"]
        for role in ("small", "large"):
            base_record = read_json(RUN / "full-frame-baseline" / role / f"{task_id}.json")
            base = compiled_view(base_record, base_frame, labels[task_id])
            for condition in CONDITIONS:
                lock = read_json(RUN / f"frame-lock-{condition}.json")
                entry = next(item for item in lock["frames"] if item["pair_task_id"] == task_id)
                record = read_json(RUN / "outputs" / role / condition / f"{task_id}.json")
                current = compiled_view(record, entry["frame"], labels[task_id])
                if (
                    current["patch"] != base["patch"]
                    or current["accepted"] != base["accepted"]
                    or current["correct"] != base["correct"]
                ):
                    changed_rows.append(
                        {
                            "task_id": task_id,
                            "repository": repo,
                            "task_family": family,
                            "role": role,
                            "condition": condition,
                            "evidence_donor_task_id": auxiliary["evidence_swap_donors"].get(task_id)
                            if condition == "evidence-swapped" else None,
                            "baseline": base,
                            "intervention": current,
                            "patch_changed": current["patch"] != base["patch"],
                            "acceptance_changed": current["accepted"] != base["accepted"],
                            "correctness_changed": current["correct"] != base["correct"],
                        }
                    )
    payload = {
        "schema_version": 1,
        "run_id": "e011-20260925-causal-evidence-01",
        "source_score_sha256": sha256((RUN / "score-e011.json").read_bytes()),
        "purpose": "post-score episode autopsy; descriptive only",
        "changed_episode_count": len(changed_rows),
        "episodes": changed_rows,
    }
    out = RUN / "episode-autopsy-e011.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"changed_episode_count": len(changed_rows), "path": str(out)}, indent=2))


if __name__ == "__main__":
    main()
