"""Merkle seal construction and recursive verification."""

from __future__ import annotations

from typing import Callable

from .identity import require_id, strict_json, typed_id


def make_seal(members: list[str], parents: list[str]) -> tuple[dict, str]:
    for identity in members + parents:
        require_id(identity)
    if len(set(members)) != len(members) or len(set(parents)) != len(parents):
        raise ValueError("duplicate seal member or parent")
    payload = {
        "schema": "KAMMI_SEAL_V1",
        "direct_members": sorted(members),
        "parents": sorted(parents),
    }
    return payload, typed_id("seal", payload)


def verify_lineage(
    root: str,
    load_seal: Callable[[str], bytes],
    verify_artifact: Callable[[str], bool],
) -> list[str]:
    closure: set[str] = set()
    visited: set[str] = set()
    visiting: set[str] = set()

    stack = [(root, False)]
    while stack:
        current, closing = stack.pop()
        if closing:
            visiting.remove(current)
            visited.add(current)
            continue
        require_id(current)
        if current in visiting:
            raise ValueError("seal ancestry cycle")
        if current in visited:
            continue
        visiting.add(current)
        payload = strict_json(load_seal(current))
        if payload.get("schema") != "KAMMI_SEAL_V1":
            raise ValueError("unsupported seal schema")
        expected, calculated = make_seal(
            payload["direct_members"], payload["parents"]
        )
        if expected != payload or calculated != current:
            raise ValueError("seal root mismatch")
        for artifact_id in payload["direct_members"]:
            if artifact_id not in closure and not verify_artifact(artifact_id):
                raise ValueError(f"missing or corrupt artifact: {artifact_id}")
            closure.add(artifact_id)
        stack.append((current, True))
        stack.extend((parent, False) for parent in reversed(payload["parents"]))
    return sorted(closure)

