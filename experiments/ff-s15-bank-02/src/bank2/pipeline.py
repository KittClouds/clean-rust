"""One world, end to end: canonical generation, derived targets, rendering, and the split predicate. Returns rows (four for TEST-TEMPLATE, one otherwise)."""
from __future__ import annotations

import copy

from . import algebra as A
from . import freeze, intents, render, splits, targets
from .canon import canonical_json, sha256_hex
from .worldgen import Reject

MAX_ATTEMPTS = 120
STRIP = ("rendered_text", "renderer_id", "renderer_family_id", "rendered_fact_ids", "mention_spans")


def structural_id(rec: dict) -> str:
    ob = {k: v for k, v in rec["OBSERVATION"].items() if k not in STRIP}
    return sha256_hex({"truth": rec["WORLD_TRUTH"], "obs": ob, "ip": rec["INFORMATION_POLICY"], "ap": rec["ACTION_POLICY"]})


def family_for(split: str, index: int) -> list[str]:
    if split == "TEST-TEMPLATE":
        return list(freeze.HELD_FAMILIES)
    if split == "TEST-JOINT":
        return [freeze.HELD_FAMILIES[index % len(freeze.HELD_FAMILIES)]]
    return [freeze.SEEN_FAMILIES[index % len(freeze.SEEN_FAMILIES)]]  # stratified and balanced over the eight seen families


def apply_rendering(rec: dict, family: str, seed=0) -> None:
    out = render.render(rec, family, seed)
    ob = rec["OBSERVATION"]
    ob["rendered_text"], ob["renderer_id"], ob["renderer_family_id"] = out["text"], f"{family}/{seed}", family
    ob["rendered_fact_ids"], ob["mention_spans"] = out["rendered_fact_ids"], out["mention_spans"]
    rec["TARGETS"]["entity"] = render.entity_target(rec, out)


def build_world(split: str, index: int, cfg=None) -> list[dict]:
    cfg = cfg or splits.cfg_for(split)
    last = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            rec = intents.generate_attempt(split, index, attempt, cfg)
            d = rec.pop("_d")
            rec["TARGETS"] = targets.compute(rec, d)
            fams = family_for(split, index)
            apply_rendering(rec, fams[0])
            feat = splits.features(rec)
            if not splits.predicate(split, feat):
                raise Reject(f"split predicate {split}: held axes {sorted(splits.held_axes(feat))}")
            rec["META"].update({"features": feat, "structural_id": structural_id(rec), "attempts": attempt + 1, "canonical_id": rec["world_id"]})
            rows = []
            for n, fam in enumerate(fams):
                row = rec if n == 0 else copy.deepcopy(rec)
                if n:
                    apply_rendering(row, fam)
                    row["world_id"] = f"{rec['world_id']}#{fam}"
                elif len(fams) > 1:
                    row["world_id"] = f"{rec['world_id']}#{fam}"
                row["META"]["textual_id"] = sha256_hex(row["OBSERVATION"]["rendered_text"])
                row["META"]["pair_id"] = rec["META"]["canonical_id"] if len(fams) > 1 else None
                rows.append(row)
            return rows
        except (Reject, A.Regenerate) as e:
            last = e
    raise RuntimeError(f"{split}:{index} not built in {MAX_ATTEMPTS} attempts: {last}")


def public_view(rec: dict) -> dict:
    """What an observer receives: no truth, no labels, no derivation."""
    ob = rec["OBSERVATION"]
    return {
        "world_id": rec["world_id"], "split": rec["split"], "renderer_id": ob["renderer_id"], "rendered_text": ob["rendered_text"],
        "actions": [{"id": a["id"], "text": render.action_text(rec, a)} for a in rec["ACTION_POLICY"]["available_actions"]],
        "requests": [{"request_id": ro["request_id"], "text": render.request_text(rec, ro)} for ro in rec["INFORMATION_POLICY"]["request_objects"]],
    }
