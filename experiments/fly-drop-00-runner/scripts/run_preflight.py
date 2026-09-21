#!/usr/bin/env python3
"""Generate the prospectively frozen RUN1 execution manifest; performs no training."""
from __future__ import annotations

import array
import hashlib
import json
import math
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "experiments" / "fly-drop-00"
RUNNER = ROOT / "experiments" / "fly-drop-00-runner"
RUN_DIR = STUDY / "artifacts" / "run-FLY-DROP-00-RUN1"
SEAL_SHA = "9dc9235c1b5ebf8c8a426f793100f9081cd1242523c27bab00331c2921e85918"
MASK = (1 << 64) - 1


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb", buffering=0) as f:
        while chunk := f.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_new_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def sm_finalizer(x: int) -> int:
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & MASK
    return (x ^ (x >> 31)) & MASK


class SplitMix64:
    def __init__(self, seed: int):
        self.state = seed & MASK

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK
        return sm_finalizer(self.state)

    def below(self, n: int) -> int:
        threshold = (1 << 64) % n
        while True:
            x = self.next()
            if x >= threshold:
                return x % n

    def open_uniform(self) -> float:
        return ((self.next() >> 12) + 1) / ((1 << 52) + 1)


def frozen_files(seal):
    records = seal["files"]
    assert len(records) == 81
    for row in records:
        path = Path(row["path"])
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            raise RuntimeError(f"sealed input missing: {path}")
        actual = sha_file(path)
        if actual != row["sha256"]:
            raise RuntimeError(f"sealed input hash mismatch: {path}")
    return [{"path": str(Path(r["path"])), "sha256": r["sha256"], "bytes": r["bytes"]} for r in records]


def verify_source(seal, manifest):
    if seal["status"] != "SEALED_PRE_TRAINING" or seal["learner_outcomes_present"] or seal["jev_in_scope"]:
        raise RuntimeError("existing seal has unexpected status or scope")
    if len(manifest["operators"]) != 41 or len(seal["operators"]) != 41:
        raise RuntimeError("sealed operator inventory is not 41")
    seal_ops = {(o["arm"], o.get("adapter_seed"), o.get("graph_seed"), o.get("control_seed")): o for o in seal["operators"]}
    seen = set()
    for op in manifest["operators"]:
        key = (op["arm"], op.get("adapter_seed"), op.get("graph_seed"), op.get("control_seed"))
        if key in seen or key not in seal_ops:
            raise RuntimeError(f"operator inventory mismatch: {key}")
        seen.add(key)
        sealed = seal_ops[key]
        if op["matrix_file"] != sealed["matrix_file"] or op["matrix_sha256"] != sealed["matrix_sha256"]:
            raise RuntimeError(f"operator metadata differs from seal: {key}")
        p = ROOT / op["matrix_file"]
        raw = p.read_bytes()
        if len(raw) != 128 * 128 * 8 or sha_bytes(raw) != op["matrix_sha256"]:
            raise RuntimeError(f"operator shape/hash mismatch: {p}")
        vals = struct.iter_unpack("<d", raw)
        for (v,) in vals:
            if not math.isfinite(v):
                raise RuntimeError(f"nonfinite operator entry: {p}")
        if op["arm"] in ("malecns", "degree", "random", "dense") and any(v < 0 for (v,) in struct.iter_unpack("<d", raw)):
            raise RuntimeError(f"nonpositive-mixing arm has a negative entry: {p}")
        if op["arm"] == "identity":
            values = [v[0] for v in struct.iter_unpack("<d", raw)]
            for r in range(128):
                for c in range(128):
                    if values[r * 128 + c] != (1.0 if r == c else 0.0):
                        raise RuntimeError("identity matrix is not bit-exact I_128")
    if len(seen) != 41:
        raise RuntimeError("operator keys are not unique")
    if len(manifest["teacher_worlds"]) != 4 or len(seal["teacher_worlds"]) != 4:
        raise RuntimeError("teacher inventory is not four worlds")
    for world in manifest["teacher_worlds"]:
        for item in world["files"]:
            p = ROOT / item["file"]
            expected = {"teacher-parameters.f32le": 16512, "train-x.f32le": 8192 * 128 * 4,
                        "train-y.u8": 8192, "heldout-x.f32le": 4096 * 128 * 4,
                        "heldout-y.u8": 4096}[p.name]
            if item["bytes"] != expected or p.stat().st_size != expected or sha_file(p) != item["sha256"]:
                raise RuntimeError(f"teacher/data file mismatch: {p}")
            if p.suffix == ".u8":
                labels = p.read_bytes()
                if any(x not in (0, 1) for x in labels):
                    raise RuntimeError(f"nonbinary labels: {p}")
                ones = sum(labels)
                counts = [len(labels) - ones, ones]
                expected_counts = world["train_class_counts"] if p.name == "train-y.u8" else world["heldout_class_counts"]
                if counts != expected_counts:
                    raise RuntimeError(f"class count differs from sealed manifest: {p}")
    if len(manifest["graphs"]) != 9:
        raise RuntimeError("graph realization count differs from seal")


def init_bytes(teacher_seed: int, learner_seed: int) -> bytes:
    seed = ((teacher_seed << 32) ^ learner_seed ^ 0x696E69742D7631) & MASK
    rng = SplitMix64(seed)
    values = bytearray()
    bound1 = math.sqrt(6.0 / (128 + 128))
    for _ in range(128 * 128):
        values.extend(struct.pack("<f", (2.0 * rng.open_uniform() - 1.0) * bound1))
    values.extend(bytes(128 * 4))
    bound2 = math.sqrt(6.0 / (128 + 1))
    for _ in range(128):
        values.extend(struct.pack("<f", (2.0 * rng.open_uniform() - 1.0) * bound2))
    values.extend(bytes(4))
    return bytes(values)


def order_bytes(teacher_seed: int, learner_seed: int) -> bytes:
    seed = ((teacher_seed << 32) ^ learner_seed ^ 0x6F726465722D7631) & MASK
    rng = SplitMix64(seed)
    out = array.array("I")
    if out.itemsize != 4 or sys.byteorder != "little":
        raise RuntimeError("runner requires little-endian 32-bit unsigned array storage")
    values = list(range(8192))
    for _ in range(20):
        for i in range(8191, 0, -1):
            j = rng.below(i + 1)
            values[i], values[j] = values[j], values[i]
        out.extend(values)
    return out.tobytes()


def operator_id(op):
    def value(name):
        item = op.get(name)
        return str(item) if item is not None else "x"
    return f"{op['arm']}-a{value('adapter_seed')}-g{value('graph_seed')}-c{value('control_seed')}"


def file_record(path: str, digest: str, byte_count: int):
    return {"path": path, "sha256": digest, "bytes": byte_count}


def main():
    if RUN_DIR.exists():
        raise RuntimeError(f"RUN1 path already exists; refusing to reuse identity: {RUN_DIR}")
    seal_path = STUDY / "PRETRAINING-SEAL.json"
    seal_sha = sha_file(seal_path)
    if seal_sha != SEAL_SHA:
        raise RuntimeError("pretraining seal SHA differs from the exact authorized identity")
    sidecar = (STUDY / "PRETRAINING-SEAL.sha256").read_text().split()[0]
    if sidecar != seal_sha:
        raise RuntimeError("seal sidecar does not match seal bytes")
    seal = read_json(seal_path)
    manifest_path = STUDY / "artifacts" / "pretraining-manifest.json"
    manifest = read_json(manifest_path)
    verify_source(seal, manifest)
    sealed = frozen_files(seal)

    run_scripts = sorted((RUNNER / "scripts").glob("*.py"))
    binary = Path(os.environ.get("FLY_DROP_RUNNER_EXE", str(RUNNER / "target" / "release" / "fly-drop-00-runner.exe")))
    if not binary.is_file():
        raise RuntimeError(f"compiled runner missing: {binary}")
    code_paths = [RUNNER / "Cargo.toml", RUNNER / "Cargo.lock", *sorted((RUNNER / "src").glob("*.rs")), *run_scripts, binary]
    run_files = [{"path": str(p), "sha256": sha_file(p), "bytes": p.stat().st_size} for p in code_paths]

    teacher_lookup = {}
    for world in manifest["teacher_worlds"]:
        files = {Path(r["file"]).name: file_record(r["file"], r["sha256"], r["bytes"]) for r in world["files"]}
        teacher_lookup[world["seed"]] = {"seed": world["seed"], "files": {
            "teacher_parameters": files["teacher-parameters.f32le"], "train_x": files["train-x.f32le"],
            "train_y": files["train-y.u8"], "heldout_x": files["heldout-x.f32le"], "heldout_y": files["heldout-y.u8"]}}

    RUN_DIR.mkdir(parents=True)
    plans = {}
    for teacher_seed in sorted(teacher_lookup):
        for learner_seed in (7101, 7102, 7103, 7104):
            key = (teacher_seed, learner_seed)
            pbytes = init_bytes(*key)
            obytes = order_bytes(*key)
            stem = f"t{teacher_seed}-l{learner_seed}"
            p_path = RUN_DIR / "plans" / f"{stem}.initial.f32le"
            o_path = RUN_DIR / "plans" / f"{stem}.order.u32le"
            p_path.parent.mkdir(parents=True, exist_ok=True)
            for path, payload in ((p_path, pbytes), (o_path, obytes)):
                with path.open("xb") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
            plans[key] = {"initial_parameters": file_record(str(p_path), sha_bytes(pbytes), len(pbytes)),
                          "minibatch_order": file_record(str(o_path), sha_bytes(obytes), len(obytes))}

    operator_inventory = []
    for op in manifest["operators"]:
        operator_inventory.append({"operator_id": operator_id(op), "arm": op["arm"],
            "adapter_seed": op.get("adapter_seed"), "graph_realization": op.get("graph_seed"),
            "control_seed": op.get("control_seed"), "matrix_file": op["matrix_file"],
            "matrix_sha256": op["matrix_sha256"], "shape": [128, 128], "dtype": "<f8"})

    fits = []
    for op in operator_inventory:
        for teacher_seed in (6101, 6102, 6103, 6104):
            for learner_seed in (7101, 7102, 7103, 7104):
                plan = plans[(teacher_seed, learner_seed)]
                t = teacher_lookup[teacher_seed]
                fit_id = f"{op['operator_id']}-t{teacher_seed}-l{learner_seed}"
                inputs = t["files"]
                fits.append({"fit_id": fit_id, "operator_id": op["operator_id"], "arm": op["arm"],
                    "adapter_seed": op["adapter_seed"], "graph_realization": op["graph_realization"],
                    "control_seed": op["control_seed"], "teacher_seed": teacher_seed, "learner_seed": learner_seed,
                    "operator_file": op["matrix_file"], "operator_sha256": op["matrix_sha256"],
                    "input_files": inputs,
                    "input_hashes": {name: rec["sha256"] for name, rec in inputs.items()},
                    "initial_parameters": plan["initial_parameters"], "minibatch_order": plan["minibatch_order"],
                    "paired_initialization_fingerprint": plan["initial_parameters"]["sha256"],
                    "paired_order_fingerprint": plan["minibatch_order"]["sha256"],
                    "expected_output_path": f"collection/fit-receipts/{fit_id}.attempt-NNNN.json"})
    if len(fits) != 656 or len({f["fit_id"] for f in fits}) != 656:
        raise RuntimeError("generated fit plan is not a unique 656-cell Cartesian product")
    paired = {}
    for fit in fits:
        key = (fit["teacher_seed"], fit["learner_seed"])
        pair = paired.setdefault(key, set())
        pair.add((fit["paired_initialization_fingerprint"], fit["paired_order_fingerprint"]))
    if len(paired) != 16 or any(len(v) != 1 for v in paired.values()):
        raise RuntimeError("paired initial parameters/order differ across operator arms")

    exec_manifest = {"schema": "FLY-DROP-00-execution-manifest-v1", "run_id": "FLY-DROP-00-RUN1",
        "seal_sha256": seal_sha, "operator_count": 41, "teacher_count": 4, "learner_seed_count": 4,
        "fit_count": 656, "operators": operator_inventory,
        "teacher_worlds": [{"seed": k, "files": v["files"]} for k, v in sorted(teacher_lookup.items())], "fits": fits}
    manifest_bytes = (json.dumps(exec_manifest, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    manifest_file = RUN_DIR / "execution-manifest.json"
    with manifest_file.open("xb") as f:
        f.write(manifest_bytes); f.flush(); os.fsync(f.fileno())

    run_contract = {"schema": "FLY-DROP-00-run-contract-v1", "run_id": "FLY-DROP-00-RUN1",
        "status": "SEALED_BEFORE_COLLECTION", "seal_sha256": seal_sha,
        "execution_manifest_sha256": sha_bytes(manifest_bytes), "fit_count": 656,
        "epochs_per_fit": 20, "updates_per_epoch": 64, "updates_per_fit": 1280,
        "total_optimizer_steps": 839680, "heldout_policy": "one terminal pass after update 1280; no earlier reads",
        "sealed_files": sealed, "run_files": run_files,
        "primary_analysis": {"contrast": "MaleCNS minus mean degree-shuffle heldout BCE",
            "bootstrap_replicates": 20000, "bootstrap_seed": 20260921,
            "bootstrap_rng": "SplitMix64 next; unbiased below-4 draws via rejection; axis draw order adapter, degree graph, teacher, learner",
            "axes": ["adapter_seed", "degree_graph_realization", "teacher_seed", "learner_seed"],
            "percentile_interval": [0.025, 0.975], "percentile_interpolation": "linear",
            "factor_consistency": "for each level, report mean paired contrast and sign; overall sign and zero levels stated; no significance tests"},
        "collection_policy": "blind collection; stdout may expose counts and health only; no comparative performance summaries",
        "numerical_failure_policy": "retain all updates and attempt; no replacement, normalization, or imputation",
        "analysis_order": ["primary contrast and bootstrap", "crossed factor summaries", "secondary controls", "accuracy and trajectories", "operator census exploratory joins"],
        "created_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
    write_new_json(RUN_DIR / "run-contract.json", run_contract)
    contract_sha = sha_file(RUN_DIR / "run-contract.json")
    with (RUN_DIR / "run-contract.sha256").open("x", encoding="ascii") as f:
        f.write(f"{contract_sha}  run-contract.json\n"); f.flush(); os.fsync(f.fileno())
    write_new_json(RUN_DIR / "preflight-receipt.json", {"run_id": "FLY-DROP-00-RUN1", "status": "PASS",
        "seal_sha256": seal_sha, "verified_sealed_file_count": len(sealed), "operator_count": 41,
        "teacher_world_count": 4, "fit_manifest_count": len(fits), "paired_cells_verified": len(paired),
        "total_optimizer_steps_declared": 839680, "outcomes_accessed": False,
        "execution_manifest_sha256": sha_bytes(manifest_bytes), "run_contract_sha256": contract_sha})
    print("RUN1 preflight PASS: 81 sealed files, 41 operators, 4 teacher worlds, 656 paired fits, 839680 declared updates; no outcomes accessed")


if __name__ == "__main__":
    main()
