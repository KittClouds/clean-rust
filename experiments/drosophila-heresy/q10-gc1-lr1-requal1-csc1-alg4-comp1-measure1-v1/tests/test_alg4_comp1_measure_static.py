from __future__ import annotations
import hashlib, json, os, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREF = ROOT.parent / 'q10-gc1-lr1-requal1-csc1-alg4-comp1-v1'
COUNT = 31_596_544
DOMAIN_SHA = 'BA9AF9234D5FF129ED584DBAE6B4133C8572E042735E84FFF7C747F8E1971CD4'

def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''): h.update(block)
    return h.hexdigest().upper()

def main() -> None:
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    assert (PREF/'CONTRACT.json').is_file()
    c=json.loads((ROOT/'CONTRACT.json').read_text())
    assert c['status']=='SEALED_PREMEASUREMENT'
    assert c['domain_count']==COUNT and c['domain_sha256']==DOMAIN_SHA
    assert c['engineering_only'] is True and c['scientific_promotion'] is False
    assert c['measurement_started'] is False
    assert c['shared_evaluation'] is True
    assert c['implementation_bindings']['runner_sha256']==sha(ROOT/'scripts/run_alg4_comp1_measure.py')
    assert c['implementation_bindings']['static_test_sha256']==sha(ROOT/'tests/test_alg4_comp1_measure_static.py')
    assert c['write_allowlist']['chunk_pattern']=='results/comp1[ab]/chunk-######.jsonl'
    assert c['max_parity_strata']==4096 and c['boundary_guard']==1e-12
    for p in ROOT.rglob('*'):
        rel=p.relative_to(ROOT).as_posix()
        if p.is_dir(): assert rel in {'scripts','tests','results','results/comp1a','results/comp1b'}, rel
        else: assert rel in c['write_allowlist']['files'] or rel in {'scripts/run_alg4_comp1_measure.py','tests/test_alg4_comp1_measure_static.py'} or re.match(r'^results/(comp1a|comp1b)/chunk-[0-9]{6}\.jsonl$',rel), rel
    print('STATIC_PASS')

if __name__=='__main__': main()
