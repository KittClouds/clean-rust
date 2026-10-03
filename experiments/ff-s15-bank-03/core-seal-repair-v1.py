"""Versioned packaging repair: protected EVAL truth includes derived root receipts.

Original frozen generator sources and data bytes remain unchanged. This repair
only places derivative truth under the same boundary before manifest/seal.
"""
import sys,shutil
from pathlib import Path
BASE=Path(__file__).resolve().parent/'core-v04'
sys.path.insert(0,str(BASE))
from common import *

def check_boundary():
    outside=[];protected=OUTPUT/'protected'
    for p in (OUTPUT/'receipts/shards').glob('*.json'):
        row=read(p)
        if row.get('split')=='EVAL' and row.get('roots'):outside.append(str(p))
    if outside:raise ValueError('Evaluation root truth outside protected boundary '+str(outside))
    for p in (OUTPUT/'public').rglob('*.gz'):
        for row in iter_rows(p):
            if any(k in row for k in ('TARGETS','SUPERVISION_ABI','WORLD_TRUTH','CAPABILITY_AXES','BOOKKEEPING')):
                raise ValueError('Public truth field '+str(p))
    return {'status':'PASS','evaluation_root_receipts_outside_protected':0,
            'public_inputs_checked':sum(2*n for n in BUDGET.values()),
            'policy':'logical role boundary, not claimed separate-user escrow'}

def main():
    verify_spec();moves=[]
    for p in sorted((OUTPUT/'receipts/shards').glob('EVAL-*.json')):
        dest=OUTPUT/'protected/evaluation-truth/receipts'/p.name
        if not dest.resolve().is_relative_to(OUTPUT.resolve()):raise ValueError('Path escaped release')
        if not p.resolve().is_relative_to(OUTPUT.resolve()):raise ValueError('Path escaped release')
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():raise ValueError('Repair destination already exists')
        h=sha(p);shutil.copyfile(p,dest)
        if sha(dest)!=h:raise ValueError('Repair changed receipt bytes')
        moves.append({'old':str(p.relative_to(OUTPUT)),'new':str(dest.relative_to(OUTPUT)),'sha256':h})
        p.unlink() # verified exact copy retained inside protected boundary
    if len(moves)!=12:raise ValueError('Expected 12 evaluation shard receipts')
    copy=OUTPUT/'source/core-seal-repair-v1.py';shutil.copyfile(__file__,copy)
    write(OUTPUT/'BOUNDARY-REPAIR-v1.json',{'identity':'CORE-v04-PACKAGING-REPAIR-v1',
      'reason':'per-root evaluation shard receipts contain derivative truth',
      'data_bytes_changed':False,'original_generator_sources_changed':False,
      'repair_source_sha256':sha(copy),'moves':moves,'boundary_gate':check_boundary()})
    print('G_PROTECTED_DERIVED_TRUTH PASS; 12 byte-identical receipts placed under protected boundary')

if __name__=='__main__':main()
