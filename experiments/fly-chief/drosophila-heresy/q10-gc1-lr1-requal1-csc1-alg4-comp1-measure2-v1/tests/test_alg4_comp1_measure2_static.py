from pathlib import Path
import hashlib,json,os,re
ROOT=Path(__file__).resolve().parents[1]
PREF=ROOT.parent/'q10-gc1-lr1-requal1-csc1-alg4-comp1-v1'
COUNT=31596544; DOMAIN='BA9AF9234D5FF129ED584DBAE6B4133C8572E042735E84FFF7C747F8E1971CD4'
R57=[34,36,49,51,53,54,60,82,98,109,133,134,153,157,161,188,205,207,238,294,322,330,345,357,381,394,398,406,423,427,430,434,447,477,496,501,507,537,574,585,586,594,597,598,626,646,675,695,696,697,700,724,737,746,747,749,768]
def sha(p):
 h=hashlib.sha256(); h.update(p.read_bytes()); return h.hexdigest().upper()
def main():
 os.environ['PYTHONDONTWRITEBYTECODE']='1'; c=json.loads((ROOT/'CONTRACT.json').read_text()); pre=json.loads((ROOT/'PREEXECUTION.json').read_text()); assert c['status']=='SEALED_PREMEASUREMENT'; assert c['domain_count']==COUNT and c['domain_sha256']==DOMAIN; assert c['target_row_count']==57 and c['target_rows']==R57; assert c['union_footprint_local_replay'] is True; assert c['max_parity_strata']==4096 and c['boundary_guard']==1e-12; assert c['engineering_only'] and not c['scientific_promotion']; assert pre['contract_sha256']==sha(ROOT/'CONTRACT.json'); assert c['implementation_bindings']['runner_sha256']==sha(ROOT/'scripts/run_alg4_comp1_measure2.py'); assert c['implementation_bindings']['static_test_sha256']==sha(ROOT/'tests/test_alg4_comp1_measure2_static.py')
 for p in ROOT.rglob('*'):
  rel=p.relative_to(ROOT).as_posix()
  if p.is_dir(): assert rel in {'scripts','tests','results','results/comp1a','results/comp1b'},rel
  else: assert rel in c['write_allowlist']['files'] or rel in {'scripts/run_alg4_comp1_measure2.py','tests/test_alg4_comp1_measure2_static.py'} or re.match(r'^results/(comp1a|comp1b)/chunk-[0-9]{6}\.jsonl$',rel),rel
 print('STATIC_PASS')
if __name__=='__main__': main()
