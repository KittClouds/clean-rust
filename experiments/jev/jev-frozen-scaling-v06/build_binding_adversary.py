"""Build a small opaque-identity binding challenge from protected test episodes."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


SOURCE = Path(r"D:\codex-runs\jev-frozen-scaling-v05\banks\feature-bank\test.jsonl")
OUT = Path(r"D:\codex-runs\jev-frozen-scaling-v06\binding-bank")
LIMIT = 256


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def candidate_index(episode: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["candidate_id"]: item for item in episode["runtime_schema"]["candidates"]}


def choice_candidate_ids(episode: dict[str, Any]) -> list[str] | None:
    sets = {
        item["candidate_set_id"]: item
        for item in episode["runtime_schema"].get("candidate_sets", [])
    }
    targets = {item["query_id"]: item for item in episode.get("gold_targets", [])}
    for query in episode.get("queries", []):
        target = targets.get(query.get("query_id"), {})
        body = target.get("target") or {}
        if body.get("target_kind") not in {"choice", "ordinal"}:
            continue
        ids = sets.get(query.get("candidate_set_id"), {}).get("candidate_ids", [])
        if len(ids) >= 2:
            return list(ids)
    return None


def main() -> None:
    ordinary: list[dict[str, Any]] = []
    adversarial: list[dict[str, Any]] = []
    for source in read_jsonl(SOURCE):
        ids = choice_candidate_ids(source)
        if not ids:
            continue
        cmap = candidate_index(source)
        first, second = cmap[ids[0]], cmap[ids[1]]
        if not first.get("opaque_id") or not second.get("opaque_id"):
            continue
        key = source["identity"]["episode_id"]
        clean = copy.deepcopy(source)
        clean["identity"]["episode_id"] = f"v06-binding-ordinary-{key}"
        clean["v06_binding_regime"] = "ordinary_opaque_definition"
        clean["v06_binding_key"] = key
        challenged = copy.deepcopy(source)
        challenged["identity"]["episode_id"] = f"v06-binding-adversarial-{key}"
        challenged["v06_binding_regime"] = "opaque_identity_conflict"
        challenged["v06_binding_key"] = key
        challenged["v06_binding_rule"] = "gold follows exposed definition, not opaque-token affinity"
        adv = candidate_index(challenged)
        adv[ids[1]]["opaque_id"] = first["opaque_id"]
        stable = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 1_000_000
        adv[ids[0]]["opaque_id"] = f"Z{stable:06d}"
        ordinary.append(clean)
        adversarial.append(challenged)
        if len(ordinary) >= LIMIT:
            break
    rows = ordinary + adversarial
    for split in ("train", "dev", "external-eval"):
        write_jsonl(OUT / f"{split}.jsonl", [])
    write_jsonl(OUT / "test.jsonl", rows)
    (OUT / "manifest.json").write_text(json.dumps({
        "protocol": "jev-frozen-decision-surface-scaling/v0.6-B",
        "ordinary_episodes": len(ordinary),
        "adversarial_episodes": len(adversarial),
        "pairs": len(ordinary),
        "gold_rule": "exposed runtime definition controls the expected semantics",
        "source": str(SOURCE),
    }, indent=2), encoding="utf-8")
    print(json.dumps({"ordinary": len(ordinary), "adversarial": len(adversarial)}))


if __name__ == "__main__":
    main()
