from __future__ import annotations
import hashlib, json, pathlib, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = pathlib.Path(r"D:\fly-pheno-00-v0.4-qreal-target")
EXE = ROOT / "sealed" / "fly-pheno-00-v0.4-qreal.exe"
MANIFEST = ROOT / "manifests/QREAL-MANIFEST.json"
CONTRACT = ROOT / "manifests/QREAL-CONTRACT.json"

def sha(p: pathlib.Path) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

def main() -> None:
    subprocess.run(["cargo","test","--release","--target-dir",str(TARGET)],cwd=ROOT/"executor",check=True)
    subprocess.run(["cargo","build","--release","--target-dir",str(TARGET)],cwd=ROOT/"executor",check=True)
    EXE.parent.mkdir(parents=True,exist_ok=True); EXE.write_bytes((TARGET/"release/fly-pheno-00-v0-4-qreal-executor.exe").read_bytes())
    paths=[MANIFEST,ROOT/"inputs/banks/training.json",ROOT/"inputs/banks/competence.json",ROOT/"inputs/banks/evaluator-large.json"]+sorted(ROOT.glob("inputs/anatomy/*.tsv"))+sorted(ROOT.glob("inputs/null-graphs/g*/edges-*.tsv"))+sorted((ROOT/"executor/src").glob("*.rs"))+[ROOT/"executor/Cargo.toml",ROOT/"executor/Cargo.lock"]
    entries=[{"path":str(p.relative_to(ROOT)).replace("\\","/"),"sha256":sha(p),"bytes":p.stat().st_size} for p in paths]
    contract={"schema":"FLY-PHENO-00-v0.4-QREAL-contract-v1","study_id":"FLY-PHENO-00-v0.4-QREAL","status":"SEALED_QUALIFICATION_ONLY","purpose":"separate representation, weight-space, native-rule, and evaluator ceilings","primary_task":"four_cue","sanity_task":"two_cue_sanity","horizon":8192,"threshold":0.25,"support_requirement":0.80,"oracle_support_requirement":0.80,"oracle_margin_report_only":0.20,"oracle_steps":128,"oracle_optimizer":"bounded deterministic gradient descent over KC->MB weights only","input_hashes":entries,"executable":"sealed/fly-pheno-00-v0.4-qreal.exe","executable_sha256":sha(EXE),"no_lesions":True,"no_recovery_comparison":True,"no_measured_execution":True,"no_seed_replacement":True}
    CONTRACT.write_text(json.dumps(contract,indent=2,sort_keys=True)+"\n",encoding="utf-8"); CONTRACT.with_suffix(".sha256").write_text(f"{sha(CONTRACT)}  {CONTRACT.name}\n",encoding="utf-8")
    print(json.dumps({"contract_sha256":sha(CONTRACT),"executable_sha256":sha(EXE)},sort_keys=True))

if __name__=="__main__": main()
