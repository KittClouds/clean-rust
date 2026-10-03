"""Freeze Q08 constructor qualification bytes; never execute a workload."""

import datetime
import hashlib
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PARENT = ROOT.parent / "dh08a/artifacts/runs/20260916T054825Z"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with pathlib.Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    require(sys.flags.optimize == 0, "optimized Python is forbidden")
    require(len(sys.argv) == 3, "usage: seal_only.py CONFIG PRESEAL_RECEIPT")
    config_path = pathlib.Path(sys.argv[1]).resolve()
    receipt_path = pathlib.Path(sys.argv[2]).resolve()
    contract = json.loads((ROOT / "CONTRACT.json").read_text())
    require(digest(ROOT / "PLAN.md") == contract["plan_sha256"], "frozen contract changed")
    require(digest(PARENT / "seal.json") == contract["parent_dh08a_seal_sha256"], "parent seal changed")
    parent_seal = json.loads((PARENT / "seal.json").read_text())
    completion = json.loads((PARENT / "completion.json").read_text())
    require(digest(PARENT / "seal.json") == completion["seal_sha256"], "parent completion mismatch")
    for name, expected in parent_seal["fingerprints"].items():
        require(digest(PARENT / "sealed" / name) == expected, f"parent frozen drift: {name}")
    for name, expected in completion["output_hashes"].items():
        require(digest(PARENT / name) == expected, f"parent output drift: {name}")

    config = json.loads(config_path.read_text())
    require(config["seeds"] == list(range(9200, 9206)), "full qualification seed set drift")
    require(config["taus"] == [4.0] and config["sides"] == ["R", "L"], "slice/tau drift")
    receipt = json.loads(receipt_path.read_text())
    require(receipt["status"] == "SAFE_FOR_FULL_CONSTRUCTOR_QUALIFICATION", "preseal receipt is not launchable")
    require(receipt["scientific_seed_bundles_used"] == 0, "preseal used scientific seeds")
    require(receipt["smoke_events_failed"] == 0, "smoke contains failed events")
    binary = ROOT / "target/release/q08-readout-null-v1.exe"
    require(str(binary.resolve()).lower().startswith(
        "d:\\drosophila-heresy\\q08-readout-null-v1-target\\"
    ), "binary target drive drift")
    require(digest(binary) == receipt["binary_sha256"], "binary differs from qualified binary")

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "artifacts" / stamp
    out.mkdir(parents=True, exist_ok=False)
    frozen = out / "frozen"
    frozen.mkdir()
    files = [ROOT / name for name in ["Cargo.toml", "Cargo.lock", "PLAN.md", "CONTRACT.json", "GEOMETRY.md"]]
    files += sorted((ROOT / "src").rglob("*.rs"))
    files += sorted((ROOT / "scripts").glob("*.py"))
    fingerprints = {}

    def copy(source, relative):
        target = frozen / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        require(digest(target) == digest(source), f"copy differs: {relative}")
        fingerprints[str(relative)] = digest(target)

    for path in files:
        copy(path, path.relative_to(ROOT))
    copy(config_path, pathlib.Path("config.json"))
    copy(receipt_path, pathlib.Path("preseal-receipt.json"))
    copy(binary, pathlib.Path(binary.name))
    for path in sorted((PARENT / "sealed/anatomy").iterdir()):
        if path.is_file():
            copy(path, pathlib.Path("anatomy") / path.name)
    require({str(path.relative_to(frozen)) for path in frozen.rglob("*") if path.is_file()}
            == set(fingerprints), "frozen manifest incomplete")
    seal = {
        "protocol": "Q08-ReadoutNull-v1",
        "kind": "CONSTRUCTOR_QUALIFICATION_ONLY",
        "before_execution": True,
        "created_utc": stamp,
        "fingerprints": fingerprints,
        "parent_seal_sha256": digest(PARENT / "seal.json"),
        "qualification_seeds": config["seeds"],
        "scientific_seed_bundles_used": 0,
        "behavioral_hypothesis_test": False,
        "python": sys.version,
        "interpreter_sha256": digest(sys.executable),
    }
    (out / "qualification-seal.json").write_text(json.dumps(seal, indent=2) + "\n")
    print(json.dumps({"frozen_qualification": str(out), "seal_sha256": digest(out / "qualification-seal.json")}, indent=2))


if __name__ == "__main__":
    main()
