from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011")
E010 = Path(r"C:\rd-c\experiment-010")
E010_RUN = E010 / "artifacts/runs/e010-20260925-cross-repo-01"
RUN_ID = "e011-20260925-causal-evidence-01"
RUN = ROOT / "artifacts/runs" / RUN_ID
HASH_TOOL = ROOT / "tools/artifact-hash.exe"
CONDITIONS = (
    "evidence-masked",
    "evidence-swapped",
    "repository-neutralized",
    "candidate-permuted",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def pretty_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def copy_once(source: Path, destination: Path) -> None:
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite frozen E011 input: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def blake3_strings(values: list[str]) -> list[str]:
    if not values:
        return []
    if not HASH_TOOL.is_file():
        raise RuntimeError(f"missing BLAKE3 helper: {HASH_TOOL}")
    with tempfile.TemporaryDirectory(prefix="e011-b3-") as temporary:
        directory = Path(temporary)
        paths: list[Path] = []
        for index, value in enumerate(values):
            path = directory / f"content-{index:04d}.bin"
            path.write_bytes(value.encode("utf-8"))
            paths.append(path)
        completed = subprocess.run(
            [str(HASH_TOOL), *[str(path) for path in paths]],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        by_path: dict[str, str] = {}
        for line in completed.stdout.splitlines():
            name, digest = line.rsplit("\t", 1)
            by_path[Path(name).name] = digest
        return [by_path[path.name] for path in paths]


def refresh_evidence_hashes(frames: list[dict]) -> None:
    evidence_rows = [entry for frame in frames for entry in frame.get("evidence", [])]
    hashes = blake3_strings([entry["content"] for entry in evidence_rows])
    for entry, digest in zip(evidence_rows, hashes, strict=True):
        entry["content_blake3"] = digest


def anonymize_repo_names(value: object) -> object:
    if isinstance(value, str):
        for repository in ("ripgrep", "turbovec"):
            value = re.sub(re.escape(repository), "repository", value, flags=re.IGNORECASE)
        return value
    if isinstance(value, list):
        return [anonymize_repo_names(item) for item in value]
    if isinstance(value, dict):
        return {key: anonymize_repo_names(item) for key, item in value.items()}
    return value


def condition_frames(base_frames: list[dict]) -> tuple[dict[str, list[dict]], dict[str, object]]:
    by_repo_variant: dict[tuple[str, int], list[dict]] = defaultdict(list)
    family_numbers = {
        family: index + 1
        for index, family in enumerate(sorted({frame["task_family"] for frame in base_frames}))
    }
    for frame in base_frames:
        by_repo_variant[(frame["repository_id"], frame["task_variant"])].append(frame)

    transformed: dict[str, list[dict]] = {name: [] for name in CONDITIONS}
    auxiliary: dict[str, object] = {
        "candidate_permutation_map": {},
        "evidence_swap_donors": {},
    }

    for original in base_frames:
        task_id = original["task_id"]

        masked = copy.deepcopy(original)
        for index, item in enumerate(masked["evidence"], start=1):
            item["source_id"] = f"redacted-source-{index}"
            item["content"] = "[task-specific evidence body removed for E011]"
        transformed["evidence-masked"].append(masked)

        swap_pool = by_repo_variant[(original["repository_id"], original["task_variant"])]
        ordered_families = sorted({item["task_family"] for item in swap_pool})
        family_index = ordered_families.index(original["task_family"])
        donor_family = ordered_families[(family_index + 1) % len(ordered_families)]
        donor = next(item for item in swap_pool if item["task_family"] == donor_family)
        swapped = copy.deepcopy(original)
        swapped["evidence"] = copy.deepcopy(donor["evidence"])
        transformed["evidence-swapped"].append(swapped)
        auxiliary["evidence_swap_donors"][task_id] = donor["task_id"]

        neutral = anonymize_repo_names(copy.deepcopy(original))
        neutral["task_id"] = f"neutral-task-{len(transformed['repository-neutralized']) + 1:02d}"
        neutral["repository_id"] = "repository-neutral"
        neutral["repository_revision"] = "revision-neutralized"
        neutral["snapshot_sha256"] = "0" * 64
        neutral["task_family"] = f"family-{family_numbers[original['task_family']]:02d}"
        transformed["repository-neutralized"].append(neutral)

        permuted = copy.deepcopy(original)
        seed = int(sha256((task_id + "|candidate-permuted").encode("utf-8"))[:16], 16)
        rng = random.Random(seed)
        shuffled = list(permuted["action_options"])
        rng.shuffle(shuffled)
        new_ids = rng.sample(range(20000, 65000), len(shuffled))
        patch_to_new_id: dict[str, int] = {}
        for option, new_id in zip(shuffled, new_ids, strict=True):
            patch_to_new_id[option["patch_sha256"]] = new_id
            option["action"]["id"] = new_id
        permuted["action_options"] = shuffled
        transformed["candidate-permuted"].append(permuted)
        auxiliary["candidate_permutation_map"][task_id] = patch_to_new_id

    for rows in transformed.values():
        refresh_evidence_hashes(rows)
    return transformed, auxiliary


def main() -> None:
    if RUN.exists() and any(RUN.iterdir()):
        raise SystemExit(f"refusing to overwrite nonempty E011 run: {RUN}")
    RUN.mkdir(parents=True, exist_ok=True)

    source_frame_lock = E010 / "tasks/heldout-bank-v1/frame-lock.json"
    source_labels = E010 / "tasks/heldout-bank-v1/sealed-labels.json"
    source_candidate_lock = E010 / "tasks/heldout-bank-v1/candidate-lock.json"
    source_split = E010 / "tasks/heldout-bank-v1/split-manifest.json"
    source_frozen = E010_RUN / "frozen-input-lock.json"
    source_prompt = E010 / "prompts/system-observer-v2.txt"
    source_schema = E010 / "schemas/observer-output.v2.json"
    source_bundle_lock = E010 / "models/bundle-lineage/v5-final/bundle-lock.json"
    source_thresholds = E010 / "models/bundle-lineage/selected-thresholds-v5.json"
    source_small = E010_RUN / "heldout-shadow-small"
    source_large = E010_RUN / "heldout-shadow-large"
    source_report = E010_RUN / "repository-level-report.md"

    copies = {
        source_frame_lock: ROOT / "inputs/e010-heldout-frame-lock.json",
        source_labels: ROOT / "inputs/e010-heldout-sealed-labels.json",
        source_candidate_lock: ROOT / "inputs/e010-heldout-candidate-lock.json",
        source_split: ROOT / "inputs/e010-heldout-split-manifest.json",
        source_frozen: ROOT / "inputs/e010-frozen-input-lock.json",
        source_prompt: ROOT / "inputs/system-observer-v2.txt",
        source_schema: ROOT / "inputs/observer-output.v2.json",
        source_bundle_lock: ROOT / "inputs/e009-v5-bundle-lock.json",
        source_thresholds: ROOT / "inputs/e009-v5-thresholds.json",
        source_report: ROOT / "inputs/e010-repository-level-report.md",
    }
    for source, destination in copies.items():
        if not source.is_file():
            raise FileNotFoundError(source)
        copy_once(source, destination)

    for role, source in (
        ("small", E010 / "models/chat-templates/minicpm5-2b-q8-local-v3.jinja"),
        ("large", E010 / "models/chat-templates/ternary-bonsai-2-27b-ptq1-local-v3.jinja"),
    ):
        copy_once(source, ROOT / f"inputs/chat-template-{role}.jinja")

    for role, source in (
        ("small", E010_RUN / "heldout-shadow-small"),
        ("large", E010_RUN / "heldout-shadow-large"),
    ):
        destination = RUN / "full-frame-baseline" / role
        if destination.exists():
            raise RuntimeError(f"refusing to overwrite baseline outputs: {destination}")
        shutil.copytree(source, destination)

    input_frame_lock = read_json(ROOT / "inputs/e010-heldout-frame-lock.json")
    base_frames = [item["frame"] for item in input_frame_lock["frames"]]
    if len(base_frames) != 16:
        raise RuntimeError(f"expected 16 E010 heldout frames, found {len(base_frames)}")
    base_by_id = {frame["task_id"]: frame for frame in base_frames}
    if len(base_by_id) != len(base_frames):
        raise RuntimeError("duplicate task IDs in E010 input bank")

    representative = base_frames[0]["evidence"][0]
    if blake3_strings([representative["content"]])[0] != representative["content_blake3"]:
        raise RuntimeError("BLAKE3 helper does not match E010 evidence contract")

    transformed, auxiliary = condition_frames(base_frames)
    for condition, frames in transformed.items():
        if len(frames) != 16:
            raise RuntimeError(f"{condition} does not preserve all 16 tasks")
        if condition == "repository-neutralized":
            if any(frame["repository_id"] != "repository-neutral" for frame in frames):
                raise RuntimeError("repository-neutralization audit failed")
            for token in ("ripgrep", "turbovec"):
                if any(re.search(token, json.dumps(frame), flags=re.IGNORECASE) for frame in frames):
                    raise RuntimeError(f"repository token {token} leaked into neutralized frames")
        if condition == "candidate-permuted":
            for frame in frames:
                ids = [item["action"]["id"] for item in frame["action_options"]]
                if len(ids) != len(set(ids)) or any(value in {11, 37, 68, 94} for value in ids):
                    raise RuntimeError("candidate IDs were not fully and uniquely permuted")

    for condition, frames in transformed.items():
        entries = []
        for index, frame in enumerate(frames):
            entries.append(
                {
                    "task_id": frame["task_id"],
                    "pair_task_id": base_frames[index]["task_id"],
                    "frame_sha256": sha256(canonical(frame)),
                    "frame": frame,
                }
            )
        pretty_write(
            RUN / f"frame-lock-{condition}.json",
            {"schema_version": 1, "condition": condition, "frames": entries},
        )

    pretty_write(RUN / "transform-auxiliary-lock.json", auxiliary)
    spec_path = ROOT / "spec/E011-causal-evidence-dependence.md"
    if not spec_path.is_file():
        raise FileNotFoundError(f"write the locked E011 spec before preparation: {spec_path}")

    sha_inputs = {
        path.relative_to(ROOT).as_posix(): sha256(path.read_bytes())
        for path in sorted((ROOT / "inputs").rglob("*"))
        if path.is_file()
    }
    sha_inputs["spec/E011-causal-evidence-dependence.md"] = sha256(spec_path.read_bytes())
    sha_inputs["scripts/prepare_e011.py"] = sha256(Path(__file__).read_bytes())
    sha_inputs["tools/artifact-hash.exe"] = sha256(HASH_TOOL.read_bytes())
    sha_inputs["e010-small-output-tree"] = tree_hash(RUN / "full-frame-baseline/small")
    sha_inputs["e010-large-output-tree"] = tree_hash(RUN / "full-frame-baseline/large")
    sha_frames = {
        condition: sha256((RUN / f"frame-lock-{condition}.json").read_bytes())
        for condition in CONDITIONS
    }

    lock = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_MODEL_CONTACT",
        "run_id": RUN_ID,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "same-bank diagnostic intervention; no promotion or transfer claim",
        "evaluation_labels": "copied from E010 after E010 scoring; previously opened and reused for paired diagnostic only",
        "model_bundles": {
            "small": "minicpm5-2b-q8-local-v5",
            "large": "ternary-bonsai-2-27b-ptq1-local-v5",
            "reasoning_mode": "off",
            "system_prompt": "E010 frozen system-observer-v2",
            "output_schema": "E010 frozen observer-output.v2",
            "normalization": "percent-0-100-to-milli-x10-v1+line-endings-lf-v1",
        },
        "routing": {
            "minimum_applicability_milli": 850,
            "maximum_abstention_milli": 150,
            "rule": "small direct action when thresholds and schema pass; otherwise large",
        },
        "conditions": list(CONDITIONS),
        "budgets_or_fitting": "none; no threshold, prompt, model, or policy fitting",
        "authority": "E002 compiled authority contract unchanged; all E011 model calls are shadow-only and cause no action effects",
        "sha256": {
            "inputs": sha_inputs,
            "transformed_frame_locks": sha_frames,
            "transform_auxiliary_lock": sha256((RUN / "transform-auxiliary-lock.json").read_bytes()),
        },
        "task_count": 16,
        "repository_count": 2,
        "full_frame_baseline_source": "copied E010 heldout-shadow-small/large outputs",
    }
    pretty_write(RUN / "frozen-input-lock.json", lock)
    print(
        json.dumps(
            {
                "run_id": RUN_ID,
                "state": lock["state"],
                "frame_sha256": sha_frames,
                "input_count": len(sha_inputs),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
