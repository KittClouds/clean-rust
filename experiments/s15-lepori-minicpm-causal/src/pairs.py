"""Renderer pairs for the Lepori causal lane.

Inherited lesson: renderer stability is a COLLAPSE DETECTOR pointed the wrong way, and raw
agreement is never a success measure. The encoder produced three global heads with ZERO
disagreement across 332 meaning-preserving pairs and majority-rate accuracy, i.e. stability that
meant nothing. So a pair is only useful here if it comes with the canonical truth attached, which
is what makes the 2x2 correctness decomposition possible.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BANK = REPO / "ff-s15-bank-01" / "releases" / "BANK-v1"
INPUTS = BANK / "inputs"


def renderer_pairs(split: str = "DEV", limit: int = 20000) -> list[dict]:
    """Meaning-preserving pairs: the same latent world rendered by different surface families.

    Grouped on the canonical world id, so both members share one latent world and therefore one
    canonical truth, which is what licenses the paired-correctness decomposition.
    """
    groups: dict[str, dict[str, str]] = {}
    n = 0
    with (INPUTS / f"{split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            n += 1
            if limit and n > limit:
                break
            wid = r["world_id"]
            base, _, fam = wid.partition("@")
            groups.setdefault(base, {})[fam or "S0"] = wid
    out = []
    for base, fams in groups.items():
        keys = sorted(fams)
        for i in range(len(keys) - 1):
            a, b = fams[keys[i]], fams[keys[i + 1]]
            if a == b:
                continue
            out.append({"a": {"world_id": a, "family": keys[i]},
                        "b": {"world_id": b, "family": keys[i + 1]},
                        "base": base})
    return out


def truth_changing_pairs(split: str = "DEV", family: str = "S1", limit: int = 2000,
                         per_world: int = 1, seed: int = 0) -> tuple[list[dict], dict]:
    """Simulator-verified pairs where candidate legality genuinely flips, same world, same
    renderer. Every emitted pair is checked against the executable simulator; a mutation that
    changes nothing is DISCARDED rather than kept as a free negative.

    This population exists to support L_CF. Because candidate-support truth is unavailable,
    L_CF stays dormant in Phase 1 and no label is invented to wake it. The pairs are built and
    receipted anyway so the capability is ready without a redesign.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bank_sim", REPO / "ff-s15-bank-01" / "src" / "simulator.py")
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)
    import random
    rng = random.Random(seed)

    worlds = {}
    with (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= limit:
                break
            if line.strip():
                w = json.loads(line)
                worlds[w["world_id"]] = w
    by_id = {}
    with (INPUTS / f"{split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if f"@{family}" in r["world_id"] or ("@" not in r["world_id"] and r["world_id"] in worlds):
                by_id.setdefault(r["world_id"], r)

    def legality(w, actions):
        st = w["initial_state"]
        keys = {json.dumps({"a": x.get("type"), "g": x.get("args", {})}, sort_keys=True)
                for x in sim.legal_actions(st, actions)}
        out = []
        for a in actions:
            k = json.dumps({"a": a.get("type"), "g": a.get("args", {})}, sort_keys=True)
            out.append(k in keys)
        return out

    out, attempts, discarded = [], 0, 0
    hist = {"flip_switch": 0, "block_edge": 0, "remove_edge": 0}
    for wid, w in worlds.items():
        row = by_id.get(wid) or by_id.get(f"{wid}@{family}")
        if row is None:
            continue
        base = list(w["available_actions"])
        if len(base) < 2:
            continue
        before = legality(w, base)
        for _ in range(per_world * 3):
            if len(out) >= limit:
                break
            attempts += 1
            mut = json.loads(json.dumps(base))
            kind = rng.choice(list(hist))
            j = rng.randrange(len(mut))
            if kind == "flip_switch":
                for f in mut[j].get("args", {}):
                    if mut[j]["args"][f] in ("open", "closed", "on", "off", True, False):
                        v = mut[j]["args"][f]
                        mut[j]["args"][f] = (not v) if isinstance(v, bool) else (
                            "closed" if v == "open" else "open")
                        hist["flip_switch"] += 1
                        break
                else:
                    attempts -= 1
                    continue
            elif kind == "block_edge":
                for f, v in list(mut[j].get("args", {}).items()):
                    if isinstance(v, str) and v.startswith("loc_") and v != "loc_0":
                        mut[j]["args"][f] = "loc_0"
                        hist["block_edge"] += 1
                        break
                else:
                    attempts -= 1
                    continue
            else:
                mut[j]["args"] = {k: v for k, v in mut[j]["args"].items() if k != "src"}
                hist["remove_edge"] += 1
            after = legality(w, mut)
            if after == before:
                discarded += 1
                continue
            out.append({"a": {"world_id": wid}, "b": {"world_id": wid},
                        "mutation": kind, "legality_changed": True,
                        "family": family})
    return out, {"emitted": len(out), "attempts": attempts, "discarded_no_flip": discarded,
                 "mutation_histogram": hist,
                 "note": "every emitted pair is simulator-verified to flip legality"}
