from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
Q=ROOT/"experiments/jev-information-density-v08q"
RUN=Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
PACKET=RUN/"q-analysis-verifier-correction-packet-v01.json"
SEAL=RUN/"q-analysis-verifier-correction-seal-v01.json"
RECORD=Q/"contracts/q-analysis-verifier-correction-v01.json"
FAILURE=RUN/"independent-verification-failure-v03.json"
RAW=RUN/"evaluation-v02/raw-predictions-v01.jsonl"
ANALYSIS_SEAL=RUN/"evaluation-v03/q-analysis-seal-v01.json"
EXPECTED_RAW="d4bc4fce5fd1c51815ac214b794e3b5d5c51f549d80ad7e1362ec5c04abc976e"
EXPECTED_ANALYSIS_ROOT="a760ed7fab0deeb81a64e9679965b8a5e172e213cde550ae804cd0370ec89ab1"
EXPECTED_ANALYSIS_SEAL="2ae62c264483df525012c35f193eef7df754e5e76ba8e5fb934b6a8391e419c9"

def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1<<20),b""):h.update(block)
    return h.hexdigest()

def write_new(path:Path,value:dict)->None:
    if path.exists():raise FileExistsError(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8",newline="\n")

def main()->None:
    if PACKET.exists() or SEAL.exists():raise RuntimeError("verifier correction packet already exists")
    if sha(FAILURE)!="b4f0fd15ed0b22bd319c77f484f7bfd44ff72c1f58f82e5a1c11801f5745e8ba" or sha(RAW)!=EXPECTED_RAW or sha(ANALYSIS_SEAL)!=EXPECTED_ANALYSIS_SEAL:
        raise RuntimeError("verifier correction parent identity mismatch")
    relative=[
      "experiments/jev-information-density-v08q/contracts/q-analysis-verifier-correction-v01.json",
      "experiments/jev-information-density-v08q/source/verify_q_full_execution_v08.py",
      "experiments/jev-information-density-v08q/source/seal_q_analysis_verifier_correction_v01.py",
      "experiments/jev-information-density-v08q/tests/test_q_verifier_bookkeeping_correction_v01.py",
    ]
    bindings=[]
    for name in sorted(relative):
        p=ROOT/name;bindings.append({"path":name,"bytes":p.stat().st_size,"sha256":sha(p)})
    root=hashlib.sha256("".join(f"{x['path']}\t{x['bytes']}\t{x['sha256']}\n" for x in bindings).encode()).hexdigest()
    packet={
      "schema":"jev-v08q-independent-verifier-correction-v01",
      "identity":"JEV-V08Q-INDEPENDENT-VERIFIER-CORRECTION-V01",
      "status":"SEALED_VERIFIER_REPAIR_READY",
      "parent_execution_packet_sha256":sha(RUN/"q-full-execution-packet-v05.json"),
      "analysis_correction_packet_sha256":sha(RUN/"q-analysis-correction-packet-v01.json"),
      "analysis_correction_seal_sha256":sha(RUN/"q-analysis-correction-seal-v01.json"),
      "analysis_seal_sha256":sha(ANALYSIS_SEAL),
      "analysis_root_sha256":EXPECTED_ANALYSIS_ROOT,
      "raw_prediction_sha256":sha(RAW),
      "failed_verifier_attempt_sha256":sha(FAILURE),
      "correction_record_sha256":sha(RECORD),
      "verifier_implementation_sha256":sha(Q/"source/verify_q_full_execution_v08.py"),
      "implementation_bindings":bindings,
      "correction_root_sha256":root,
      "analysis_outputs_changed":False,
      "prediction_matrix_changed":False,
      "created_at_utc":datetime.now(timezone.utc).isoformat()
    }
    write_new(PACKET,packet)
    seal={"status":"Q_VERIFIER_CORRECTION_PACKET_SEALED","packet_sha256":sha(PACKET),"root_sha256":root,"output_count":len(bindings),"outputs":bindings,"builder_sha256":sha(Path(__file__).resolve())}
    write_new(SEAL,seal)
    print(json.dumps({"packet_sha256":sha(PACKET),"correction_root_sha256":root,"seal_sha256":sha(SEAL),"bound_files":len(bindings)},indent=2))

if __name__=="__main__":main()
