from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PARENT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-exh1-v1"
PROTOCOL = "Q10-ALG3-EXH1-AUDIT1"
IDENTITY = ROOT.name


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def audit() -> dict[str, Any]:
    contract = json.loads((PARENT / "CONTRACT.json").read_text(encoding="utf-8"))
    execution = json.loads((PARENT / "execution.json").read_text(encoding="utf-8"))
    require(execution["status"] == "ALG3_EXH1_COMPLETE", "parent is not complete")
    require(int(execution["counts"]["structural_triples"]) == 125_506_560, "parent structural cardinality drift")
    for binding in contract["parent_bindings"]:
        path = REPO / binding["path"]
        require(path.is_file(), f"missing bound parent: {path}")
        require(digest(path) == str(binding["sha256"]).upper(), f"parent binding drift: {binding['label']}")

    allowed_files = {"PLAN.md", "CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json"}
    actual_files = {path.relative_to(PARENT).as_posix() for path in PARENT.iterdir() if path.is_file()}
    require(actual_files == allowed_files, f"unexpected EXH1 root files: {sorted(actual_files - allowed_files)}")
    allowed_dirs = {"scripts", "valid-frontier", "range-summaries"}
    actual_dirs = {path.name for path in PARENT.iterdir() if path.is_dir()}
    require(actual_dirs == allowed_dirs, f"unexpected EXH1 root directories: {sorted(actual_dirs - allowed_dirs)}")
    require(not (PARENT / "scripts" / "__pycache__").exists(), "EXH1 pycache present")

    totals = Counter()
    contexts = []
    for context in execution["contexts"]:
        context_name = f"{context['context'][0].removesuffix('.json')}__set{context['context'][1]}"
        ranges = sorted(context["ranges"], key=lambda item: int(item["start"]))
        cursor = 0
        valid_total = 0
        n1_counts = Counter()
        n2_counts = Counter()
        payload_records = 0
        seen_ranks: set[int] = set()
        for item in ranges:
            start, end = int(item["start"]), int(item["end"])
            require(start == cursor and end > start, f"noncontiguous range: {context_name} {start}-{end}")
            shard = REPO / item["valid_shard"]
            require(shard.is_file(), f"missing valid shard: {shard}")
            payload_hash = hashlib.sha256()
            count = 0
            with shard.open("rb") as stream:
                for raw in stream:
                    payload_hash.update(raw)
                    record = json.loads(raw)
                    rank = int(record["local_rank"])
                    global_rank = int(record["global_rank"])
                    require(start <= rank < end, f"valid rank outside range: {shard} {rank}")
                    require(rank not in seen_ranks, f"duplicate valid rank: {context_name} {rank}")
                    seen_ranks.add(rank)
                    require(record["context"] == context["context"], f"record context drift: {shard}")
                    n1, n2 = int(record["n1"]), int(record["n2"])
                    require(0 <= n1 <= 3 and 0 <= n2 <= 3, f"bad rescue labels: {shard}")
                    pair_bits = record["pair_valid_bits"]
                    require(len(pair_bits) == 3 and sum(bool(value) for value in pair_bits) == n2, f"pair label drift: {shard}")
                    expected_class = {3: "PAIRWISE_VALID_TRIANGLE", 2: "ONE_PAIR_RESCUED", 1: "TWO_PAIR_RESCUED", 0: "PURE_HIGHER_ORDER_RESCUE"}[n2]
                    require(record["rescue_class"] == expected_class, f"rescue class drift: {shard}")
                    require(global_rank >= 0, f"negative global rank: {shard}")
                    count += 1
                    valid_total += 1
                    n1_counts[n1] += 1
                    n2_counts[n2] += 1
            require(count == int(item["valid"]), f"valid count drift: {shard}")
            require(payload_hash.hexdigest().upper() == str(item["valid_payload_sha256"]).upper(), f"valid payload hash drift: {shard}")
            cursor = end
        require(cursor == int(context["structural_triples"]), f"context range coverage drift: {context_name}")
        require(valid_total == int(context["valid_triples"]), f"context valid total drift: {context_name}")
        expected_n1 = {int(k): int(v) for k, v in context["valid_n1"].items()}
        expected_n2 = {int(k): int(v) for k, v in context["valid_n2"].items()}
        require(dict(sorted(n1_counts.items())) == expected_n1, f"n1 aggregate drift: {context_name}")
        require(dict(sorted(n2_counts.items())) == expected_n2, f"n2 aggregate drift: {context_name}")
        totals["structural_triples"] += int(context["structural_triples"])
        totals["valid_triples"] += valid_total
        totals["payload_records"] += payload_records + valid_total
        contexts.append({"context": context["context"], "ranges": len(ranges), "structural_triples": int(context["structural_triples"]), "valid_triples": valid_total, "n1": dict(sorted(n1_counts.items())), "n2": dict(sorted(n2_counts.items())), "unique_valid_ranks": len(seen_ranks)})
    require(totals["structural_triples"] == 125_506_560, "global structural total drift")
    require(totals["valid_triples"] == int(execution["counts"]["valid_triples"]), "global valid total drift")
    return {"protocol": PROTOCOL, "identity": IDENTITY, "status": "EXH1_AUDIT_COMPLETE", "engineering_only": True, "scientific_promotion": False, "parent_execution_sha256": digest(PARENT / "execution.json"), "parent_contract_sha256": digest(PARENT / "CONTRACT.json"), "counts": dict(totals), "contexts": contexts, "conclusion": "EXH1 range coverage, valid payloads, rescue labels, parent bindings, and write surface reconciled independently."}


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(not (ROOT / "execution.json").exists(), "audit execution already exists")
    write_new(ROOT / "CONTRACT.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parent": {"path": PARENT.relative_to(REPO).as_posix(), "execution_sha256": digest(PARENT / "execution.json"), "contract_sha256": digest(PARENT / "CONTRACT.json")}, "read_only": True, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json"]})
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json")})
    try:
        result = audit()
        write_new(ROOT / "execution.json", result)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": result["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_EXH1_AUDIT", "engineering_only": True, "scientific_promotion": False, "error_type": type(exc).__name__, "error": str(exc)}
        write_new(ROOT / "execution.json", result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
