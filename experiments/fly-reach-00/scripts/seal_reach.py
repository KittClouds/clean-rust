from __future__ import annotations
import hashlib,json,pathlib,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]; TARGET=pathlib.Path(r"D:\fly-reach-00-target"); EXE=ROOT/"sealed/fly-reach-00.exe"; MANIFEST=ROOT/"manifests/REACH-MANIFEST.json"; CONTRACT=ROOT/"manifests/REACH-CONTRACT.json"
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""):h.update(b)
 return h.hexdigest()
def main():
 subprocess.run(["cargo","test","--release","--target-dir",str(TARGET)],cwd=ROOT/"executor",check=True); subprocess.run(["cargo","build","--release","--target-dir",str(TARGET)],cwd=ROOT/"executor",check=True)
 EXE.parent.mkdir(parents=True,exist_ok=True); EXE.write_bytes((TARGET/"release/fly-reach-00-executor.exe").read_bytes())
 paths=[MANIFEST,ROOT/"inputs/banks/training.json",ROOT/"inputs/banks/competence.json",ROOT/"inputs/banks/evaluator-large.json"]+sorted(ROOT.glob("inputs/anatomy/*.tsv"))+sorted(ROOT.glob("inputs/null-graphs/g*/edges-*.tsv"))+sorted((ROOT/"executor/src").glob("*.rs"))+[ROOT/"executor/Cargo.toml",ROOT/"executor/Cargo.lock"]
 entries=[{"path":str(p.relative_to(ROOT)).replace("\\","/"),"sha256":sha(p),"bytes":p.stat().st_size} for p in paths]
 c={"schema":"FLY-REACH-00-contract-v1","study_id":"FLY-REACH-00","status":"SEALED_ENGINEERING_ONLY","purpose":"decompose native adaptive authority into magnitude, direction, and support","primary_task":"four_cue","horizon":8192,"threshold":0.25,"support_requirement":0.80,"reference_lr":0.05,"oracle_lr":0.5,"oracle_steps":128,"arms":["native","native_direction_reference_magnitude","reference_direction_native_support","reference_direction_full_support","weight_oracle"],"diagnostics":["proposed_delta","delivered_delta","cosine_native_reference","native_reference_norm_ratio","native_support_fraction","reference_mass_on_native_support","bound_clip_fraction","cumulative_displacement"],"input_hashes":entries,"executable":"sealed/fly-reach-00.exe","executable_sha256":sha(EXE),"no_lesions":True,"no_biological_promotion":True,"no_pheno_reseal":True}
 CONTRACT.write_text(json.dumps(c,indent=2,sort_keys=True)+"\n",encoding="utf-8"); CONTRACT.with_suffix(".sha256").write_text(f"{sha(CONTRACT)}  {CONTRACT.name}\n",encoding="utf-8"); print(json.dumps({"contract_sha256":sha(CONTRACT),"executable_sha256":sha(EXE)},sort_keys=True))
if __name__=="__main__":main()
