"""Shared helpers for the C0 tests: fixture loading, a mutable copy of the fixture records, subprocess runs."""
from __future__ import annotations

import copy
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from s15 import canon, model, runtime  # noqa: E402

FIX = ROOT / "fixtures"
CASES = sorted(p.name for p in (FIX / "cases").iterdir() if p.is_dir())


def read(path):
    return canon.loads_strict(Path(path).read_bytes())


def fixture_world() -> model.World:
    return model.load_world(FIX / "policy.json", FIX / "contracts", FIX / "bundles")


def case_inputs(name: str) -> tuple[dict, dict]:
    return read(FIX / "cases" / name / "observation.json"), read(FIX / "cases" / name / "vector.json")


def expected_bytes(name: str) -> bytes:
    return (FIX / "cases" / name / "expected-receipt.json").read_bytes()


def expected_receipt(name: str) -> dict:
    return read(FIX / "cases" / name / "expected-receipt.json")


def reseal_vector(vector: dict) -> dict:
    return model.seal(canon.without(vector, "decision_vector_id") | {"schema": "S15_DECISION_VECTOR_V1"})


def with_outputs(vector: dict, world: model.World, **outputs) -> dict:
    """Returns a resealed vector where the given aliases carry new ppm lists (None drops the alias)."""
    entries = {e["bundle_id"]: dict(e) for e in vector["entries"]}
    for alias, ppm in outputs.items():
        bundle_id = world.alias_bundle[alias]["bundle_id"]
        if ppm is None:
            entries.pop(bundle_id, None)
        else:
            entries.setdefault(bundle_id, {"bundle_id": bundle_id})["probabilities_ppm"] = list(ppm)
    return reseal_vector({**vector, "entries": [entries[k] for k in sorted(entries)]})


def shuffled(value, rng: random.Random):
    """Same document, dictionary keys in a random order (list order is meaning, so it is kept)."""
    if isinstance(value, dict):
        keys = list(value)
        rng.shuffle(keys)
        return {k: shuffled(value[k], rng) for k in keys}
    if isinstance(value, list):
        return [shuffled(v, rng) for v in value]
    return value


class Records:
    """A mutable copy of the fixture policy, contracts and bundles that can be written out and loaded."""

    def __init__(self):
        self.policy = read(FIX / "policy.json")
        self.contracts = {p.stem: read(p) for p in sorted((FIX / "contracts").glob("*.json"))}
        self.bundles = {p.stem: read(p) for p in sorted((FIX / "bundles").glob("*.json"))}

    def write(self, root: Path, encode=canon.canonical_bytes):
        (root / "contracts").mkdir(parents=True, exist_ok=True)
        (root / "bundles").mkdir(parents=True, exist_ok=True)
        for name, record in self.contracts.items():
            (root / "contracts" / f"{name}.json").write_bytes(encode(record))
        for name, record in self.bundles.items():
            (root / "bundles" / f"{name}.json").write_bytes(encode(record))
        (root / "policy.json").write_bytes(encode(self.policy))
        return root / "policy.json", root / "contracts", root / "bundles"

    def world(self, root: Path) -> model.World:
        return model.load_world(*self.write(root))


class Base(unittest.TestCase):
    def tmp(self) -> Path:
        directory = Path(tempfile.mkdtemp(prefix="s15-test-"))
        self.addCleanup(shutil.rmtree, directory, True)
        return directory

    def edited_world(self, mutate, seal: bool = True) -> model.World:
        """Loads the fixture world with `mutate(policy)` applied (and the policy resealed)."""
        records = Records()
        mutate(records.policy)
        if seal:
            records.policy = model.seal(records.policy)
        return records.world(self.tmp())

    def policy_rejected(self, mutate, fragment: str = "", seal: bool = True):
        with self.assertRaises(model.RecordError) as raised:
            self.edited_world(mutate, seal)
        self.assertIn(fragment, str(raised.exception))

    def run_case(self, world, observation, vector) -> dict:
        receipt, data = runtime.run(world, observation, vector)
        self.assertEqual(data, canon.canonical_bytes(receipt))
        return receipt


def python(*args, cwd=None, env=None, flags=()):
    """Runs `python -m s15 ...` in a subprocess with the package importable from anywhere."""
    environment = {**os.environ, "PYTHONPATH": str(ROOT), **(env or {})}
    return subprocess.run([sys.executable, *flags, "-m", "s15", *map(str, args)], cwd=cwd, env=environment, capture_output=True, timeout=120)


def deep(value):
    return copy.deepcopy(value)
