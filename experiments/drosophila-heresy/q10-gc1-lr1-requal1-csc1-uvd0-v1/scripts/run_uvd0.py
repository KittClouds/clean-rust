from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
SINGLES = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-singles-v1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def line_hash(path: Path) -> str:
    return sha(path)


def verify_inputs(contract: dict) -> None:
    require(contract["identity"] == ROOT.name and contract["status"] == "SEALED_PREMEASUREMENT", "UVD0 contract drift")
    pre = json.loads((ROOT / "PREEXECUTION.json").read_text(encoding="utf-8"))
    require(pre["contract_sha256"] == sha(ROOT / "CONTRACT.json"), "UVD0 contract hash drift")
    for binding in contract["parent_bindings"]:
        path = REPO / binding["path"]
        require(path.is_file(), f"missing bound input: {binding['path']}")
        require(path.stat().st_size == int(binding["bytes"]), f"bound byte drift: {binding['path']}")
        require(sha(path) == binding["sha256"], f"bound hash drift: {binding['path']}")


def main() -> int:
    if os.environ.get("PYTHONDONTWRITEBYTECODE") != "1":
        raise RuntimeError("PYTHONDONTWRITEBYTECODE must be 1")
    for name in ("execution.json", "STATUS.json"):
        require(not (ROOT / name).exists(), f"refusing existing output: {name}")
    contract = json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))
    verify_inputs(contract)
    execution = json.loads((SINGLES / "execution.json").read_text(encoding="utf-8"))
    require(execution["status"] == "SREPLACE_SINGLETONS_COMPLETE", "singleton parent incomplete")
    total_singletons = 0
    total_pairs = 0
    context_meta = []
    output_paths: list[Path] = []
    for slug in contract["contexts"]:
        source = SINGLES / "shards" / f"{slug}.jsonl"
        rows = json.loads(source.read_text(encoding="utf-8"))
        total_singletons += len(rows)
        require(len(rows) % 8 == 0, f"singleton shard cardinality is not group-aligned: {slug}")
        by_group: dict[int, list[dict]] = {}
        for row in rows:
            group = int(row["group"])
            by_group.setdefault(group, []).append(row)
        require(all(len(items) == 8 for items in by_group.values()), f"singleton alternatives drift: {slug}")
        actions = []
        for group, items in sorted(by_group.items()):
            for row in sorted(items, key=lambda value: str(value["to"])):
                mapping = tuple((int(c), int(choice)) for c, choice in row["canonical_mapping"])
                coordinates = frozenset(c for c, _ in mapping)
                require(mapping and len(coordinates) == len(mapping), f"malformed singleton action: {slug} {group}")
                actions.append((group, str(row["to"]), coordinates, row))
        pairs: list[str] = []
        pair_index = 0
        for left_index, left in enumerate(actions):
            for right in actions[left_index + 1:]:
                if left[0] == right[0] or left[2].intersection(right[2]):
                    continue
                pair = {
                    "pair_index": pair_index,
                    "case": slug,
                    "a": {"group": left[0], "to": left[1]},
                    "b": {"group": right[0], "to": right[1]},
                }
                pairs.append(json.dumps(pair, sort_keys=True, separators=(",", ":")) + "\n")
                pair_index += 1
        output = ROOT / "shards" / f"{slug}.jsonl"
        require(not output.exists(), f"output already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("".join(pairs), encoding="utf-8", newline="\n")
        output_paths.append(output)
        total_pairs += pair_index
        context_meta.append({"context": slug, "singleton_actions": len(actions), "groups": len(by_group), "structurally_eligible_pairs": pair_index, "domain_sha256": line_hash(output)})
    require(total_singletons == 3696, f"singleton count drift: {total_singletons}")
    domain_manifest = {"protocol": "Q10-CSC1-UVD0", "identity": ROOT.name, "contexts": context_meta, "ordered_domain_sha256": hashlib.sha256("".join(str(item["domain_sha256"]) for item in context_meta).encode()).hexdigest().upper(), "pair_count": total_pairs, "pair_outcomes_consulted": False, "pair_replay_performed": False}
    (ROOT / "execution.json").write_text(json.dumps({"protocol": "Q10-CSC1-UVD0", "identity": ROOT.name, "status": "UVD0_COMPLETE", "engineering_only": True, "scientific_promotion": False, "pair_outcomes_consulted": False, "pair_replay_performed": False, "counts": {"contexts": len(context_meta), "singleton_actions": total_singletons, "structurally_eligible_pairs": total_pairs}, "contexts": context_meta, "domain_manifest": domain_manifest}, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "STATUS.json").write_text(json.dumps({"protocol": "Q10-CSC1-UVD0", "identity": ROOT.name, "status": "UVD0_COMPLETE", "engineering_only": True, "scientific_promotion": False, "pair_outcomes_consulted": False, "pair_replay_performed": False}, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": "UVD0_COMPLETE", "contexts": len(context_meta), "singleton_actions": total_singletons, "structurally_eligible_pairs": total_pairs}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
