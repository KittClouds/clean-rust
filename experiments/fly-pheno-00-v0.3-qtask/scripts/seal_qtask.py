from __future__ import annotations
import hashlib
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = pathlib.Path(r"D:\fly-pheno-00-v0.3-qtask-target")
EXE = ROOT / "sealed" / "fly-pheno-00-v0.3-qtask.exe"
MANIFEST = ROOT / "manifests" / "QTASK-MANIFEST.json"
CONTRACT = ROOT / "manifests" / "QTASK-CONTRACT.json"

def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def main() -> None:
    subprocess.run(["cargo", "test", "--release", "--target-dir", str(TARGET)], cwd=ROOT / "executor", check=True)
    subprocess.run(["cargo", "build", "--release", "--target-dir", str(TARGET)], cwd=ROOT / "executor", check=True)
    EXE.parent.mkdir(parents=True, exist_ok=True)
    built = TARGET / "release" / "fly-pheno-00-v0-3-qtask-executor.exe"
    EXE.write_bytes(built.read_bytes())
    paths = [MANIFEST, ROOT / "inputs/banks/training.json", ROOT / "inputs/banks/competence.json"]
    paths += sorted(ROOT.glob("inputs/anatomy/*.tsv")) + sorted(ROOT.glob("inputs/null-graphs/g*/edges-*.tsv"))
    paths += sorted((ROOT / "executor/src").glob("*.rs")) + [ROOT / "executor/Cargo.toml", ROOT / "executor/Cargo.lock"]
    entries = [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(p), "bytes": p.stat().st_size} for p in paths]
    contract = {
        "schema":"FLY-PHENO-00-v0.3-QTASK-contract-v1", "study_id":"FLY-PHENO-00-v0.3-QTASK",
        "status":"SEALED_QUALIFICATION_ONLY", "purpose":"select hardest common stationary task rung before PHENO measurement",
        "difficulty_axis":"cue_count", "difficulty_order":["T1","T2","T3","T4"],
        "rung_cues":{"T1":16,"T2":12,"T3":8,"T4":4}, "horizons":[512,1024,2048,4096,8192],
        "threshold":0.25, "margin_threshold":0.20, "support_requirement":0.80,
        "substrates":["fly", *[f"g{i:03d}" for i in range(1,9)]], "sides":["L","R"],
        "learner_task_blocks":list(range(32000,32012)), "graph_seeds":list(range(33000,33008)), "response_seed":36000,
        "selection_rule":"hardest rung with >=80% competent cells and median loss <=0.20 for every substrate at horizon 8192",
        "input_hashes":entries, "executable":"sealed/fly-pheno-00-v0.3-qtask.exe", "executable_sha256":sha(EXE),
        "no_lesions":True, "no_recovery_comparison":True, "no_measured_execution":True, "no_seed_replacement":True,
    }
    CONTRACT.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    CONTRACT.with_suffix(".sha256").write_text(f"{sha(CONTRACT)}  {CONTRACT.name}\n", encoding="utf-8")
    print(json.dumps({"contract_sha256":sha(CONTRACT),"executable_sha256":sha(EXE)},sort_keys=True))

if __name__ == "__main__": main()
