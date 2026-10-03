"""Freeze DH03 inputs, execute once, verify lineage, and analyze frozen outputs."""
import ctypes
import datetime
import hashlib
import json
import pathlib
import platform
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PARENT_DH04 = ROOT.parent / "dh04/artifacts/runs/20260912T044912Z"
PARENT_DH03 = ROOT.parent / "dh03/artifacts/runs/20260912T042145Z"
PARENT_DH02 = ROOT.parent / "dh02/artifacts/runs/20260912T040045Z"
PARENT_DH01 = ROOT.parent / "artifacts/runs/20260912T032529Z"


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify_archived_run(run):
    completion = json.loads((run / "completion.json").read_text())
    seal = json.loads((run / "seal.json").read_text())
    assert digest(run / "seal.json") == completion["seal_sha256"]
    for name, expected in completion["output_hashes"].items():
        assert digest(run / name) == expected, (run, name)
    for name, expected in seal["fingerprints"].items():
        assert digest(run / "sealed" / name) == expected, (run, name)
    return {
        "seal_sha256": completion["seal_sha256"],
        "frozen_files": len(seal["fingerprints"]),
        "output_files": len(completion["output_hashes"]),
    }, seal


def verify_parents():
    dh04, dh04_seal = verify_archived_run(PARENT_DH04)
    dh03, dh03_seal = verify_archived_run(PARENT_DH03)
    dh02, dh02_seal = verify_archived_run(PARENT_DH02)
    dh01, _ = verify_archived_run(PARENT_DH01)
    assert dh04_seal["parent_dh03"]["seal_sha256"] == dh03["seal_sha256"]
    assert dh03_seal["parent_dh02"]["seal_sha256"] == dh02["seal_sha256"]
    assert dh02_seal["parent_dh01"]["seal_sha256"] == dh01["seal_sha256"]
    inherited = [
        "src/allocation.rs",
        "src/baseline.rs",
        "src/graph.rs",
        "src/observer.rs",
        "src/plasticity.rs",
        "src/rng.rs",
        "src/task.rs",
        "src/simulation/dh03.rs",
        "src/simulation/experiment.rs",
    ]
    for name in inherited:
        key = str(pathlib.Path(name))
        assert digest(ROOT / name) == dh04_seal["fingerprints"][key], name
    return dh04, dh03, dh02, dh01


class Memory(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
    ] + [
        (name, ctypes.c_size_t)
        for name in [
            "PeakWorkingSetSize",
            "WorkingSetSize",
            "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage",
            "PagefileUsage",
            "PeakPagefileUsage",
        ]
    ]


def run():
    dh04, dh03, dh02, dh01 = verify_parents()
    config = json.loads((ROOT / "config.json").read_text())
    dh04_config = json.loads((PARENT_DH04 / "sealed/config.json").read_text())
    dh03_config = json.loads((PARENT_DH03 / "sealed/config.json").read_text())
    dh02_config = json.loads((PARENT_DH02 / "sealed/config.json").read_text())
    dh01_config = json.loads((PARENT_DH01 / "sealed/config.json").read_text())
    assert not set(config["seeds"]) & set(dh04_config["seeds"])
    assert not set(config["seeds"]) & set(dh03_config["seeds"])
    assert not set(config["seeds"]) & set(dh02_config["seeds"])
    assert not set(config["seeds"]) & set(dh01_config["seeds"])
    assert len(config["seeds"]) == len(set(config["seeds"]))

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "artifacts/runs" / stamp
    out.mkdir(parents=True, exist_ok=False)
    frozen = out / "sealed"
    frozen.mkdir()
    files = [
        ROOT / name
        for name in [
            "Cargo.toml",
            "Cargo.lock",
            "config.json",
            "PROTOCOL.md",
            "QUALIFICATION.json",
        ]
    ]
    files += sorted((ROOT / "src").rglob("*.rs"))
    files += sorted((ROOT / "scripts").glob("*.py"))
    files += sorted((ROOT / "qualification").glob("*.log"))
    fingerprints = {}
    for path in files:
        relative = path.relative_to(ROOT)
        target = frozen / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        fingerprints[str(relative)] = digest(target)
        assert fingerprints[str(relative)] == digest(path)

    anatomy = frozen / "anatomy"
    anatomy.mkdir()
    for path in sorted((PARENT_DH04 / "sealed/anatomy").iterdir()):
        if path.is_file():
            shutil.copy2(path, anatomy / path.name)
            fingerprints[str(pathlib.Path("anatomy") / path.name)] = digest(path)

    binary = ROOT / "target/release/drosophila-heresy-dh05.exe"
    assert str(binary.resolve()).lower().startswith("d:\\drosophila-heresy\\dh05-target\\")
    shutil.copy2(binary, frozen / binary.name)
    fingerprints[binary.name] = digest(binary)
    seal = {
        "protocol": "DH-05",
        "created_utc": stamp,
        "before_task_execution": True,
        "fingerprints": fingerprints,
        "parent_dh04": dh04,
        "parent_dh03": dh03,
        "parent_dh02": dh02,
        "parent_dh01": dh01,
        "common_immediate_acquisition": True,
        "causal_factor": "distractor_generated_eligibility",
        "both_causal_cells_restore_interval_state": True,
        "fresh_seed_bundles": config["seeds"],
        "dh05_outcomes_used_for_tuning": 0,
        "python": sys.version,
        "platform": platform.platform(),
        "binary_executed": str(binary),
        "binary_resolved": str(binary.resolve()),
        "compiler": subprocess.check_output(["rustc", "--version"], text=True).strip(),
    }
    (out / "seal.json").write_text(json.dumps(seal, indent=2) + "\n")
    print("FROZEN_RUN", out, flush=True)
    print("SEAL_SHA256", digest(out / "seal.json"), flush=True)

    query = ctypes.WinDLL("psapi").GetProcessMemoryInfo
    query.argtypes = [ctypes.c_void_p, ctypes.POINTER(Memory), ctypes.c_ulong]
    query.restype = ctypes.c_int
    start = time.perf_counter()
    peak = 0
    last = start
    with (out / "stdout.log").open("w") as log:
        process = subprocess.Popen(
            [str(binary), "run", str(frozen / "config.json"), str(anatomy), str(out)],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        while process.poll() is None:
            counters = Memory()
            counters.cb = ctypes.sizeof(counters)
            if query(
                ctypes.c_void_p(int(process._handle)),
                ctypes.byref(counters),
                counters.cb,
            ):
                peak = max(peak, counters.PeakWorkingSetSize)
            now = time.perf_counter()
            if now - last >= 30:
                print(
                    "running_seconds",
                    round(now - start, 1),
                    "peak_working_set_bytes",
                    peak,
                    flush=True,
                )
                last = now
            time.sleep(0.1)
    resources = {
        "exit_code": process.returncode,
        "wall_seconds_including_launch": time.perf_counter() - start,
        "observed_peak_working_set_bytes": peak,
        "method": "Windows GetProcessMemoryInfo peak working set sampled every 0.1 s; simulator only",
    }
    (out / "resources.json").write_text(json.dumps(resources, indent=2) + "\n")
    assert process.returncode == 0, (out / "stdout.log").read_text()
    for name, expected in fingerprints.items():
        assert digest(frozen / name) == expected, name
    assert verify_parents() == (dh04, dh03, dh02, dh01)
    assert digest(binary) == fingerprints[binary.name]
    subprocess.run(
        [sys.executable, str(frozen / "scripts/analyze.py"), str(out)], check=True
    )
    completion = {
        "seal_sha256": digest(out / "seal.json"),
        "parent_dh04_reverified": True,
        "parent_dh03_reverified": True,
        "parent_dh02_reverified": True,
        "parent_dh01_reverified": True,
        "frozen_inputs_reverified": True,
        "resources": resources,
        "output_hashes": {
            path.name: digest(path) for path in out.iterdir() if path.is_file()
        },
    }
    (out / "completion.json").write_text(json.dumps(completion, indent=2) + "\n")
    print("COMPLETE", out, flush=True)


if __name__ == "__main__":
    run()
