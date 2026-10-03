"""Canonical JSON, content hashes and seeded randomness. No wall clock, no global random state."""
from __future__ import annotations

import hashlib
import json
import random


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(data) -> str:
    if not isinstance(data, (bytes, bytearray)):
        data = canonical_json(data).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def short(obj, n: int = 12) -> str:
    return sha256_hex(obj)[:n]


def rng(*parts) -> random.Random:
    """A Random seeded from the hash of its parts, so any derived quantity is reproducible from (seed, label)."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    return random.Random(int.from_bytes(h[:16], "big"))
