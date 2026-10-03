"""Freeze DH-08A, execute its only measured run, and analyze archived output."""

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
DH_ROOT = ROOT.parent
PARENT_DH07R = DH_ROOT / "dh07r/artifacts/runs/20260915T233614Z"
Q07 = DH_ROOT / "q07-bounded-null-v1/artifacts/20260915T215754Z"
Q07_GATES = DH_ROOT / "q07-bounded-null-v1/artifacts/20260915T215102Z/holdout-gates.json"

if sys.flags.optimize != 0:
    raise RuntimeError("DH-08A sealing forbids optimized Python because integrity checks must execute")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with pathlib.Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify_archived_run(run):
    completion = json.loads((run / "completion.json").read_text())
    seal = json.loads((run / "seal.json").read_text())
    assert digest(run / "seal.json") == completion["seal_sha256"]
    for name, expected in seal["fingerprints"].items():
        assert digest(run / "sealed" / name) == expected, (run, name)
    for name, expected in completion["output_hashes"].items():
        assert digest(run / name) == expected, (run, name)
    return {"seal_sha256": completion["seal_sha256"], "frozen_files": len(seal["fingerprints"])}


def verify_q07():
    seal = json.loads((Q07 / "qualification-seal.json").read_text())
    policy = json.loads((Q07 / "policy-summary.json").read_text())
    independent = json.loads((Q07 / "policy-independent.json").read_text())
    assert seal["before_execution"] and seal["measured_seeds_forbidden"] == list(range(7000, 7032))
    assert policy["status"] == "CLOSED_LOOP_QUALIFICATION_PASSED"
    assert policy["events"] == 12_288 and policy["failures"] == [] and policy["measured_seeds_used"] == 0
    assert digest(Q07_GATES) == policy["gates_sha256"]
    assert independent["summary"]["independent_checks"] == 384
    assert independent["summary"]["no_behavioral_hypothesis_test"] is True
    for name, expected in seal["fingerprints"].items():
        require(digest(Q07 / "frozen" / name) == expected, f"Q07 fingerprint drift: {name}")
    q_rotation = Q07 / "frozen/src/rotation.rs"
    require(digest(ROOT / "src/rotation.rs") == digest(q_rotation), "Q07 rotation implementation drift")
    return {
        "seal_sha256": digest(Q07 / "qualification-seal.json"),
        "policy_summary_sha256": digest(Q07 / "policy-summary.json"),
        "independent_summary_sha256": digest(Q07 / "policy-independent.json"),
        "events": policy["events"],
        "measured_seeds_used": 0,
    }


def verify_qualification_receipt():
    receipt = json.loads((ROOT / "QUALIFICATION.json").read_text())
    require(receipt["status"] == "QUALIFIED_FOR_SINGLE_MEASURED_EXECUTION", "qualification status is not launchable")
    require(receipt["fresh_measured_seeds_used"] == 0, "qualification opened measured seeds")
    require(receipt["constructor_qualification"]["closed_loop_events"] == 12_288, "Q07 event count drift")
    require(receipt["constructor_qualification"]["failures"] == 0, "Q07 contains failures")
    require(receipt["exact_orchestration_smoke"]["fresh_measured_seeds_used"] == 0, "smoke opened measured seeds")
    require(receipt["rust"]["tests_failed"] == 0 and receipt["analysis"]["tests_failed"] == 0,
            "qualification test receipt contains failures")
    runtime = receipt["runtime"]
    require(digest(pathlib.Path(sys.executable)) == runtime["interpreter_sha256"],
            "analysis interpreter hash differs from qualified runtime")
    require(sys.version == runtime["python"], "Python version differs from qualified runtime")
    locked = (ROOT / "requirements.lock").read_text().strip()
    require(locked == f"numpy=={runtime['numpy']}", "requirements lock differs from qualification")
    active_numpy = subprocess.check_output(
        [sys.executable, "-c", "import numpy; print(numpy.__version__)"], text=True
    ).strip()
    require(active_numpy == runtime["numpy"], "NumPy version differs from qualified runtime")
    smoke = receipt["exact_orchestration_smoke"]
    require(smoke["seed"] == 9100 and smoke["event_count"] == 1_024,
            "qualification smoke cardinality drift")
    require(smoke["all_events_passed"] and smoke["fresh_measured_seeds_used"] == 0,
            "qualification smoke failed")
    for name, expected in smoke["output_hashes"].items():
        require(digest(ROOT / "qualification/output" / name) == expected,
                f"qualification smoke hash mismatch: {name}")
    return receipt


def ensure_unopened():
    runs = ROOT / "artifacts/runs"
    require(not (runs / "DH08A_MEASURED_SEEDS_OPENED.json").exists(),
            "repository-wide measured-seed claim already exists")
    for directory in runs.glob("*"):
        if not directory.is_dir():
            continue
        require(not (directory / "MEASURED_SEEDS_OPENED.json").exists(),
                f"measured seeds were already opened by {directory}")
        require(not list(directory.glob("R-tau*.jsonl")) and not list(directory.glob("L-tau*.jsonl")),
                f"partial measured output already exists in {directory}")


def checked(command, log_name):
    path = ROOT / "qualification" / log_name
    with path.open("w") as log:
        completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    require(completed.returncode == 0, f"pre-seal command failed; see {path}")


def qualify_frozen_binary(binary, output, log_path, config_path=None, anatomy=None):
    require(not output.exists(), "frozen-binary qualification output already exists")
    config_path = config_path or ROOT / "qualification/config.json"
    anatomy = anatomy or PARENT_DH07R / "sealed/anatomy"
    with log_path.open("w") as log:
        completed = subprocess.run(
            [str(binary), "qualify", str(config_path),
             str(anatomy), str(output)],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
        )
    require(completed.returncode == 0, "current binary qualification failed")
    execution = json.loads((output / "execution.json").read_text())
    require(execution["mode"] == "qualify" and execution["fresh_seed_bundles"] == 0,
            "current qualification touched measured seeds")
    bundles = []
    for side in ["R", "L"]:
        for tau in [4, 16]:
            records = (output / f"{side}-tau{tau}.jsonl").read_text().splitlines()
            require(len(records) == 1, "current qualification bundle count drift")
            bundle = json.loads(records[0])
            require(bundle["seed"] == 9100 and bundle["side"] == side and bundle["tau"] == tau,
                    "current qualification identity drift")
            require(len(bundle["results"]) == 2, "current qualification cell count drift")
            bundles.append(bundle)
    maxima = {name: 0.0 for name in [
        "axial_error_over_total_norm", "norm_relative_error",
        "residual_norm_relative_error", "residual_abs_cosine",
    ]}
    gates = {
        "axial_error_over_total_norm": 1e-7,
        "norm_relative_error": 1e-7,
        "residual_norm_relative_error": 1e-7,
        "residual_abs_cosine": 1e-5,
    }
    event_count = 0
    expected_keys = {("E", "true_perpendicular"), ("Z", "true_perpendicular")}
    for bundle in bundles:
        result_keys = [(row["arm"], row["condition"]) for row in bundle["results"]]
        require(len(result_keys) == len(set(result_keys)) and set(result_keys) == expected_keys,
                "current qualification result-cell membership drift")
        for row in bundle["results"]:
            if row["arm"] == "E":
                events = row["shadow"]["events"]
                require(row["shadow"]["status"] == "PASSED" and len(events) == 256,
                        "current qualification manipulation failed")
                event_count += len(events)
                for expected_trial, event in enumerate(events, 1):
                    require(event["trial"] == expected_trial, "qualification event order drift")
                    require(event["geometry_valid"] is True, "geometry-valid receipt failed")
                    require(event["shadow_hot_allocations"] == 0, "shadow allocation gate failure")
                    require(abs(event["true_minus_null"] -
                                (event["true_margin"] - event["null_margin"])) <= 1e-15,
                            "shadow contrast arithmetic drift")
                    geometry = event["geometry"]
                    for name in maxima:
                        maxima[name] = max(maxima[name], geometry[name])
                    require(geometry["boundary_symmetric_difference"] == 0, "boundary mismatch")
                    require(geometry["outside_support_changes"] == 0, "outside-support change")
                    require(geometry["max_bound_violation"] == 0 and geometry["hot_allocations"] == 0,
                            "bound or constructor-allocation gate failure")
                    support_error = abs(geometry["true_nonzero"] - geometry["null_nonzero"]) / max(
                        geometry["true_nonzero"], 1
                    )
                    require(support_error <= 0.01, "support-size gate failure")
            else:
                require(row["shadow"]["status"] == "FIXED_WEIGHT_CONTROL" and
                        row["shadow"]["events"] == [], "fixed-weight shadow control drift")
    for name, gate in gates.items():
        require(maxima[name] <= gate, f"{name} gate failure")
    require(event_count == 1_024, "current qualification event cardinality drift")
    summary = {
        "status": "PASSED", "seed": 9100, "fresh_measured_seeds_used": 0,
        "result_cells": 8, "shadow_events": event_count, "observed_maxima": maxima,
        "output_hashes": {
            f"{side}-tau{tau}.jsonl": digest(output / f"{side}-tau{tau}.jsonl")
            for side in ["R", "L"] for tau in [4, 16]
        },
        "binary_sha256": digest(binary),
    }
    return summary


def run_preseal_checks():
    ensure_unopened()
    qualification = verify_qualification_receipt()
    checked(["cargo", "test", "--release"], "preseal-cargo-test.log")
    checked(["cargo", "clippy", "--all-targets", "--all-features", "--", "-D", "warnings"],
            "preseal-cargo-clippy.log")
    checked(["cargo", "build", "--release"], "preseal-cargo-build.log")
    checked([sys.executable, "-m", "unittest", "scripts/test_analysis.py", "-v"],
            "preseal-python-analysis-tests.log")
    binary = ROOT / "target/release/drosophila-heresy-dh08a.exe"
    require(str(binary.resolve()).lower().startswith("d:\\drosophila-heresy\\dh08a-target\\"),
            "release binary did not resolve to target drive")
    return qualification, binary


class Memory(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
        (name, ctypes.c_size_t)
        for name in [
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
        ]
    ]


def copy_frozen(path, frozen, fingerprints):
    relative = path.relative_to(ROOT)
    target = frozen / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    fingerprints[str(relative)] = digest(target)
    assert fingerprints[str(relative)] == digest(path)


def run():
    qualification, binary = run_preseal_checks()
    parent = verify_archived_run(PARENT_DH07R)
    q07 = verify_q07()
    config = json.loads((ROOT / "config.json").read_text())
    assert config["seeds"] == list(range(8000, 8032)) and len(set(config["seeds"])) == 32
    old = json.loads((PARENT_DH07R / "sealed/config.json").read_text())
    assert not set(config["seeds"]) & set(old["seeds"]), PARENT_DH07R
    require("Status before measured execution: `FROZEN_UNOPENED`." in
            (ROOT / "PROTOCOL.md").read_text(), "protocol is not frozen")

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "artifacts/runs" / stamp
    out.mkdir(parents=True, exist_ok=False)
    frozen = out / "sealed"
    frozen.mkdir()
    files = [ROOT / name for name in [
        "Cargo.toml", "Cargo.lock", "config.json", "PROTOCOL.md",
        "QUALIFICATION.json", "requirements.lock",
    ]]
    files += sorted((ROOT / "src").rglob("*.rs"))
    files += sorted((ROOT / "scripts").glob("*.py"))
    files += sorted((ROOT / "qualification").glob("*.log"))
    files += sorted((ROOT / "qualification").glob("*.json"))
    fingerprints = {}
    for path in files:
        copy_frozen(path, frozen, fingerprints)

    anatomy = frozen / "anatomy"
    anatomy.mkdir()
    for path in sorted((PARENT_DH07R / "sealed/anatomy").iterdir()):
        if path.is_file():
            target = anatomy / path.name
            shutil.copy2(path, target)
            fingerprints[str(pathlib.Path("anatomy") / path.name)] = digest(target)

    q_evidence = frozen / "q07-evidence"
    q_evidence.mkdir()
    for path in [
        Q07 / "qualification-seal.json", Q07 / "policy-summary.json",
        Q07 / "policy-independent.json", Q07 / "clamp-summary.json", Q07_GATES,
    ]:
        target = q_evidence / path.name
        shutil.copy2(path, target)
        fingerprints[str(target.relative_to(frozen))] = digest(target)

    frozen_binary = frozen / binary.name
    shutil.copy2(binary, frozen_binary)
    fingerprints[binary.name] = digest(frozen_binary)

    smoke_output = out / "preseal-qualification"
    current_smoke = qualify_frozen_binary(
        frozen_binary,
        smoke_output,
        out / "preseal-qualification.log",
        frozen / "qualification/config.json",
        anatomy,
    )
    require(current_smoke["binary_sha256"] == fingerprints[binary.name],
            "qualified binary differs from frozen binary")
    smoke_receipt = frozen / "current-binary-smoke.json"
    smoke_receipt.write_text(json.dumps(current_smoke, indent=2) + "\n")
    fingerprints[str(smoke_receipt.relative_to(frozen))] = digest(smoke_receipt)
    frozen_files = {
        str(path.relative_to(frozen)) for path in frozen.rglob("*") if path.is_file()
    }
    require(frozen_files == set(fingerprints), "sealed file manifest is incomplete")

    seal = {
        "protocol": "DH-08A",
        "created_utc": stamp,
        "before_task_execution": True,
        "status_at_seal": "FROZEN_UNOPENED",
        "fingerprints": fingerprints,
        "parent_dh07r": parent,
        "q07_qualification": q07,
        "dh08a_qualification": qualification,
        "current_binary_smoke": current_smoke,
        "fresh_seed_bundles": config["seeds"],
        "fresh_seed_outcomes_used_for_tuning": 0,
        "primary_outcome": "seed mean of event-local true_minus_null old-map margins",
        "primary_contrast": "mean(M_true - M_Q07_matched_null) over 2 sides x 2 taus x 256 events",
        "python": sys.version,
        "analysis_interpreter": sys.executable,
        "analysis_interpreter_sha256": digest(pathlib.Path(sys.executable)),
        "analysis_numpy": qualification["runtime"]["numpy"],
        "platform": platform.platform(),
        "binary_executed": str(frozen_binary),
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
            [str(frozen_binary), "run", str(frozen / "config.json"), str(anatomy), str(out)],
            stdout=log, stderr=subprocess.STDOUT,
        )
        while process.poll() is None:
            counters = Memory()
            counters.cb = ctypes.sizeof(counters)
            if query(ctypes.c_void_p(int(process._handle)), ctypes.byref(counters), counters.cb):
                peak = max(peak, counters.PeakWorkingSetSize)
            now = time.perf_counter()
            if now - last >= 30:
                print("running_seconds", round(now - start, 1), "peak_working_set_bytes", peak, flush=True)
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
    assert verify_archived_run(PARENT_DH07R) == parent
    assert verify_q07() == q07
    subprocess.run([sys.executable, str(frozen / "scripts/analyze.py"), str(out)], check=True)

    output_hashes = {}
    for path in sorted(out.rglob("*")):
        if not path.is_file() or frozen in path.parents or path.name in {"seal.json", "completion.json"}:
            continue
        output_hashes[str(path.relative_to(out))] = digest(path)
    actual_outputs = {
        str(path.relative_to(out)) for path in out.rglob("*")
        if path.is_file() and frozen not in path.parents
        and path.name not in {"seal.json", "completion.json"}
    }
    require(actual_outputs == set(output_hashes), "output file manifest is incomplete")
    completion = {
        "seal_sha256": digest(out / "seal.json"),
        "global_open_marker_sha256": digest(ROOT / "artifacts/runs/DH08A_MEASURED_SEEDS_OPENED.json"),
        "parent_dh07r_reverified": True,
        "q07_reverified": True,
        "frozen_inputs_reverified": True,
        "resources": resources,
        "output_hashes": output_hashes,
    }
    (out / "completion.json").write_text(json.dumps(completion, indent=2) + "\n")
    print("COMPLETE", out, flush=True)


if __name__ == "__main__":
    run()
