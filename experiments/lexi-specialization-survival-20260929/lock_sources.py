"""Bind the already prepared NER and NLI inputs as independent arms."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_outputs(lock: dict, paths: dict[str, Path]) -> None:
    for split, path in paths.items():
        item = lock["prepared"][split]
        digest = sha256(path)
        if digest != item["sha256"]:
            raise ValueError(f"prepared {split} hash mismatch: {digest}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--openner-lock", type=Path, required=True)
    ap.add_argument("--openner-data", type=Path, required=True)
    ap.add_argument("--nli-lock", type=Path, required=True)
    ap.add_argument("--nli-data", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    ner_lock = json.loads(args.openner_lock.read_text(encoding="utf-8"))
    nli_lock = json.loads(args.nli_lock.read_text(encoding="utf-8"))
    ner_source = ner_lock["arms"]["openner_en"]
    if ner_lock.get("bank_v1_used_for_training") is not False:
        raise ValueError("OpenNER source receipt does not exclude BANK-v1 training")
    if nli_lock.get("bank_v1_used_for_training") is not False:
        raise ValueError("NLI source receipt does not exclude BANK-v1 training")
    ner_paths = {split: args.openner_data / f"{split}.jsonl"
                 for split in ("train", "dev", "test")}
    nli_paths = {split: args.nli_data / f"{split}.jsonl"
                 for split in ("train", "validation_matched", "validation_mismatched")}
    check_outputs(ner_source, ner_paths)
    check_outputs(nli_lock, nli_paths)

    def files(lock: dict, paths: dict[str, Path]) -> dict:
        return {split: {"path": str(path.resolve()), "rows": lock["prepared"][split]["rows"],
                        "sha256": lock["prepared"][split]["sha256"]}
                for split, path in paths.items()}

    result = {
        "schema": "phoenix.lexi-specialization-survival/source-lock-v1",
        "status": "READY_FOR_FROZEN_HEAD_CONTROLS",
        "arms_are_independent": True,
        "bank_v1_used_for_training": False,
        "ner": {
            "dataset": ner_source["repo"], "revision": ner_source["revision"],
            "license": ner_source["note"], "source_lock_sha256": sha256(args.openner_lock),
            "source_lock_path": str(args.openner_lock.resolve()),
            "sources": ner_source["sources"], "splits": files(ner_source, ner_paths),
        },
        "nli": {
            "dataset": nli_lock["dataset"], "revision": nli_lock["dataset_revision"],
            "config": nli_lock["config"], "license": nli_lock["license"],
            "source_lock_sha256": sha256(args.nli_lock),
            "source_lock_path": str(args.nli_lock.resolve()),
            "splits": files(nli_lock, nli_paths),
        },
        "policy": {
            "training": "each arm reads only its own train split",
            "selection": "own development/validation splits; no BANK TEST tuning",
            "no_cross_arm_concatenation": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True,
                                      indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "lock_sha256": sha256(args.output),
                      "output": str(args.output.resolve()),
                      "ner_rows": {k: v["rows"] for k, v in result["ner"]["splits"].items()},
                      "nli_rows": {k: v["rows"] for k, v in result["nli"]["splits"].items()}},
                     sort_keys=True))


if __name__ == "__main__":
    main()
