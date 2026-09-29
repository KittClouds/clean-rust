"""Builds C0 observations and decision vectors from DEV rows and prerecorded observer outputs."""
from __future__ import annotations

from .common import ACTIONS, canon, model, sha256_bytes


def observation_id(world_id: str) -> str:
    """BANK ids look like DEV:000009:0:0 and, for paired renderers, DEV:000009:0:0@S1; C0 names allow neither ':' nor '@'. Injective."""
    return world_id.replace(":", "-").replace("@", "_at_")


def observation(world_id: str, world_hash: str, family: str) -> dict:
    """All 14 BANK actions are granted and none forbidden: BANK has no authority ground truth (see the preregistration)."""
    return {
        "schema": "S15_OBSERVATION_V1", "observation_id": observation_id(world_id), "state_hash": "sha256:" + sha256_bytes(world_hash.encode("ascii")), "actor": "bank_eval",
        "facts": {"surface_family": family}, "authority_state": {"granted_actions": sorted(ACTIONS), "forbidden_actions": [], "flags": {}},
    }


def vector(world_id: str, dec_bundle_id: str, act_bundle_id: str, dec_ppm, act_ppm, source: str) -> dict:
    entries = [{"bundle_id": dec_bundle_id, "probabilities_ppm": [int(v) for v in dec_ppm]}, {"bundle_id": act_bundle_id, "probabilities_ppm": [int(v) for v in act_ppm]}]
    return model.seal({
        "schema": "S15_DECISION_VECTOR_V1", "observation_id": observation_id(world_id), "producer": {"kind": "PRERECORDED", "source": source},
        "entries": sorted(entries, key=lambda e: e["bundle_id"]),
    })


def write_records(directory, records: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, record in records.items():
        (directory / f"{name}.json").write_bytes(canon.canonical_bytes(record))
