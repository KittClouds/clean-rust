"""Prepare fresh engineering-only FLY-REACH inputs."""
from __future__ import annotations
import hashlib, importlib.util, json, pathlib, sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE_PREP=ROOT.parent/"fly-pheno-00"/"qualification"/"prepare_contract.py"
ANATOMY,GRAPHS,BANKS,MANIFESTS=ROOT/"inputs/anatomy",ROOT/"inputs/null-graphs",ROOT/"inputs/banks",ROOT/"manifests"
SIDES=("L","R"); SUBSTRATES=("fly",)+tuple(f"g{i:03d}" for i in range(1,9)); BLOCKS=tuple(range(52000,52012)); GRAPH_SEEDS=tuple(range(53000,53008)); RESPONSE_SEED=56000; LARGE_RESPONSE_SEED=57000; PRETRAIN_TRIALS=8192; CUES=4; DELAY_STEPS=12

def sha(p:pathlib.Path)->str:
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""): h.update(b)
 return h.hexdigest()
def write(p,v): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def lineage():
 spec=importlib.util.spec_from_file_location("reach_prepare_lineage",SOURCE_PREP); m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)
 m.ROOT,m.ANATOMY,m.GRAPHS=ROOT,ANATOMY,GRAPHS; m.MANIFESTS=MANIFESTS; m.SIDES=SIDES; m.SUBSTRATES=SUBSTRATES; m.GRAPH_SEEDS=GRAPH_SEEDS; return m
def schedule(m,seed):
 r=m.SplitMix64(seed); labels=[i%2==0 for i in range(CUES)]; order=list(range(CUES)); r.shuffle(order); labels=[labels[i] for i in order]; rows=[]
 for _ in range(PRETRAIN_TRIALS):
  row=[r.index(CUES)]; row.extend(CUES+r.index(32) for _ in range(DELAY_STEPS)); rows.append(row)
 return labels,rows
def draws(m,seed,n):
 r=m.SplitMix64(seed); return [[r.next() for _ in range(16)] for _ in range(n)]
def main():
 for p in (ANATOMY,GRAPHS,BANKS,MANIFESTS): p.mkdir(parents=True,exist_ok=True)
 m=lineage(); sides={s:m.read_nodes(s) for s in SIDES}; m.prepare_null_graphs(sides)
 blocks={}
 for b in BLOCKS:
  seed=b+100000; labels,rows=schedule(m,seed^0x545241494E); blocks[str(b)]={"task_seed":seed,"labels":labels,"schedule":rows,"cue_count":CUES}
 write(BANKS/"training.json",{"schema":"FLY-REACH-00-training-bank-v1","qualification_only":True,"cues":CUES,"pretraining_trials":PRETRAIN_TRIALS,"delay_steps":DELAY_STEPS,"blocks":blocks})
 for name,seed,n in (("competence.json",RESPONSE_SEED,256),("evaluator-large.json",LARGE_RESPONSE_SEED,4096)):
  write(BANKS/name,{"schema":f"FLY-REACH-00-{name[:-5]}-bank-v1","seed":seed,"n_eval":n,"draw_shape":[n,16],"response_draws_u64":draws(m,seed,n),"training_never_reads":True})
 files=lambda pats:[{"path":str(p.relative_to(ROOT)).replace("\\","/"),"sha256":sha(p),"bytes":p.stat().st_size} for pat in pats for p in sorted(ROOT.glob(pat))]
 write(MANIFESTS/"REACH-MANIFEST.json",{"schema":"FLY-REACH-00-manifest-v1","study_id":"FLY-REACH-00","purpose":"engineering-only decomposition of native adaptive authority","substrates":list(SUBSTRATES),"sides":list(SIDES),"blocks":list(BLOCKS),"graph_seeds":list(GRAPH_SEEDS),"primary_task":"four_cue","pretraining_trials":PRETRAIN_TRIALS,"threshold":0.25,"support_requirement":0.80,"arms":["native","native_direction_reference_magnitude","reference_direction_native_support","reference_direction_full_support","weight_oracle"],"reference_lr":0.05,"oracle_steps":128,"checkpoints":[0,512,1024,2048,4096,8192],"source_files":files(["inputs/anatomy/*.tsv"]),"null_files":files(["inputs/null-graphs/g*/edges-*.tsv"]),"bank_files":files(["inputs/banks/*.json"]),"no_lesions":True,"no_biological_promotion":True})
 print(json.dumps({"study":"FLY-REACH-00","blocks":len(BLOCKS),"graphs":len(GRAPH_SEEDS),"cues":CUES},sort_keys=True))
if __name__=="__main__": main()
