from pathlib import Path
import hashlib,json,os
ROOT=Path(__file__).resolve().parents[1]
MEASURE=ROOT.parent/'q10-gc1-lr1-requal1-csc1-alg4-comp1-measure1-v1'
ALLOW={'PLAN.md','CONTRACT.json','PREEXECUTION.json','execution.json','STATUS.json','REPORT.md','tests','tests/test_abort_audit_static.py'}
def sha(p):
 h=hashlib.sha256(); h.update(p.read_bytes()); return h.hexdigest().upper()
def main():
 os.environ['PYTHONDONTWRITEBYTECODE']='1'; c=json.loads((ROOT/'CONTRACT.json').read_text()); pre=json.loads((ROOT/'PREEXECUTION.json').read_text()); assert c['reason']=='NONPROMOTABLE_SCOPE_DEFECT'; assert c['pid']==5480 and c['result_chunk_count']==0; assert pre['contract_sha256']==sha(ROOT/'CONTRACT.json'); assert c['measure1_contract_sha256']==sha(MEASURE/'CONTRACT.json');
 for p in ROOT.rglob('*'): assert p.relative_to(ROOT).as_posix() in ALLOW
 print('STATIC_PASS')
if __name__=='__main__': main()
