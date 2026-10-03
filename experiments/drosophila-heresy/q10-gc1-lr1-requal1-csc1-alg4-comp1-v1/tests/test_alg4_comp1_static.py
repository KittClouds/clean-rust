from __future__ import annotations
import hashlib, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COUNT = 31_596_544

def sha(path: Path) -> str:
    h=hashlib.sha256();
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest().upper()

def main() -> int:
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    contract=json.loads((ROOT/'CONTRACT.json').read_text(encoding='utf-8'))
    pre=json.loads((ROOT/'PREEXECUTION.json').read_text(encoding='utf-8'))
    dom=json.loads((ROOT/'preflight-domain.json').read_text(encoding='utf-8'))
    assert contract['status']=='SEALED_PREMEASUREMENT'
    assert pre['contract_sha256']==sha(ROOT/'CONTRACT.json')
    assert pre['domain_count']==EXPECTED_COUNT and dom['domain_count']==EXPECTED_COUNT
    assert contract['domain_classes']['COMP1A']==contract['domain_classes']['COMP1B']
    assert contract['measurement_started'] is False and contract['scientific_promotion'] is False
    assert contract['geometry_prefilter'] is False
    assert json.loads((ROOT/'anchors/a3_manifest.json').read_text())['anchor_rows']==[161,357,749]
    assert json.loads((ROOT/'anchors/footprint_manifest.json').read_text())['excluded_count']==6
    assert sha(ROOT/'scripts/run_alg4_comp1.py')==contract['implementation_bindings']['runner_sha256']
    assert sha(ROOT/'tests/test_alg4_comp1_static.py')==contract['implementation_bindings']['static_test_sha256']
    allowed=set(contract['write_allowlist'])
    for p in ROOT.rglob('*'):
        rel=p.relative_to(ROOT).as_posix()
        assert rel in allowed, rel
    print('STATIC_PASS')

if __name__=='__main__': main()
