"""Independent audit for the completed Q10-NA pair/triple replay receipts."""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path
from typing import Any


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    protocol = Path(__file__).resolve().parents[1]
    contract = load(protocol / "CONTRACT.json")
    preflight = load(protocol / "qualification" / "preflight.json")
    pair = load(protocol / "qualification" / "pair-full.json")
    triple = load(protocol / "qualification" / "triple-full.json")
    require(contract["protocol"] == "Q10-NA" and contract["version"] == 2, "contract identity/version")
    require(digest(protocol / "PLAN.md") == contract["plan_sha256"], "plan hash drift")
    require(pair["stage"] == "PAIR_REPLAY_FULL" and pair["triple_replay_executed"] is False, "pair stage drift")
    require(triple["stage"] == "TRIPLE_REPLAY_PAIR_NEGATIVE_TAIL", "triple stage drift")
    require(pair["scientific_seed_bundles_used"] == 0 and triple["scientific_seed_bundles_used"] == 0, "scientific bundles")
    require(pair["behavioral_inference"] is False and triple["behavioral_inference"] is False, "behavioral inference")
    require(pair["canonical_repair_applied"] is False and triple["canonical_repair_applied"] is False, "canonical repair")
    require(pair["dh08b_authorized"] is False and triple["dh08b_authorized"] is False, "DH08B authorization")

    pair_records = pair["records"]
    triple_records = triple["records"]
    pair_keys = {tuple(item["target"]) for item in pair_records}
    triple_keys = {tuple(item["target"]) for item in triple_records}
    require(len(pair_records) == 324 and len(pair_keys) == 324, "pair target identity count")
    require(len(triple_records) == 111 and len(triple_keys) == 111, "triple target identity count")
    require(triple_keys <= pair_keys, "triple target is absent from pair receipt")
    require(all(item["pair_domain_complete"] for item in pair_records), "pair domain incomplete")
    require(sum(item["pair_replays"] for item in pair_records) == 1_493_624, "pair replay count")
    require(pair["remaining_pair_budget"] == 25_000_000 - 1_493_624, "pair budget receipt")
    require(sum(item["triple_replays"] for item in triple_records) == 15_868_182, "triple replay count")
    require(triple["triple_replays"] == 15_868_182, "triple receipt replay count")
    require(triple["projected_triple_domain"] == 15_868_182, "triple projected domain")
    require(all(item["triple_domain_complete"] for item in triple_records), "triple domain incomplete")

    pair_classes = collections.Counter(item["classification"] for item in pair_records)
    triple_classes = collections.Counter(item["classification"] for item in triple_records)
    require(pair_classes == {"pair": 213, "no-effect-within-complete-domain": 111}, "pair class partition")
    require(triple_classes == {"triple": 16, "no-effect-within-complete-domain": 95}, "triple class partition")
    pair_negative = {tuple(item["target"]) for item in pair_records if item["classification"] == "no-effect-within-complete-domain"}
    require(pair_negative == triple_keys, "triple tail is not exactly pair-negative")
    require(sum(1 for item in pair_records if item["best"] is not None and item["best"]["candidate_ulp"] == 0) == 202, "pair exact-bit count")
    require(sum(1 for item in triple_records if item["best"] is not None and item["best"]["candidate_ulp"] == 0) == 16, "triple exact-bit count")

    require(preflight["targets"]["observed"] == 326, "preflight target count")
    require(preflight["targets"]["empty_support_summary"]["empty_support_count"] == 2, "empty target count")
    require(preflight["cost_projection"]["pair"]["exact_total_candidates"] == 1_493_624, "preflight pair total")
    require(preflight["cost_projection"]["triple"]["exact_total_candidates"] == 61_058_294, "preflight triple total")

    forbidden = {"accuracy", "reward", "actions", "behavior", "old_map_margin", "reversed_map_margin", "scientific_seed_id"}
    for receipt in (pair, triple):
        keys = {str(key).lower() for key in receipt}
        require(not keys.intersection(forbidden), "forbidden top-level field")
    print(
        "Q10-NA replay audit passed: pair_rows=213 triple_rows=16 "
        "no_effect_after_triples=95 empty_support=2 pair_replays=1493624 "
        "triple_replays=15868182"
    )
    print("Q10-NA scientific/behavioral interpretation: closed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, TypeError, ValueError, AuditError) as error:
        raise SystemExit(f"Q10-NA replay audit failed: {error}") from error
