"""Full hash/binding validation and fresh original-Qwen prefix sample replay."""
import os
os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8'
from common import *
from late_access import CACHE,load_tower,pilot_lock
from extract import hidden

def main():
    setup();pilot_lock();tokenizer,tower,identity=load_tower();h=read(BANK/'PHASE5-HANDOFF-v02.json');counts={}
    for split in ('TRAIN','DEV'):
        cached=list((CACHE/split).glob('*.pt'));validated=0;binding_metadata={}
        abi=load(C6/f'{split}-ABI.pt');d=dataset_load(split);sample=load(CACHE/split/'00000.pt');wanted={r['row_id']:r for r in sample};public={}
        for p in cached:
            for r in load(p):
                if r['row_id']!=d['row_ids'][int(abi['row_index'][r['index']])]:raise ValueError('prefix binding identity')
                if r['prefix'].ndim!=2 or r['prefix'].shape[1]!=1024 or len(r['prefix'])>1415:raise ValueError('prefix shape')
                binding_metadata[r['row_id']]=r['candidate_entities']
                validated+=1
        if validated!=len(abi['row_index']):raise ValueError('prefix row count')
        for n,digest in h['splits'][split]['input_files'].items():
            if sha(BANK/n)!=digest:raise ValueError('public source drift')
            for r in rows(BANK/n):
                if r['world_id'] in binding_metadata:
                    lookup={b['id']:i for i,b in enumerate(r['bindings'])}
                    args=[[lookup.get(a['args'][key],-1) for key in sorted(a['args'])]+[-1]*(4-len(a['args'])) for a in r['actions']]
                    args += [[-1]*4]*(171-len(args))
                    if not torch.equal(torch.tensor(args,dtype=torch.int16),binding_metadata[r['world_id']]):raise ValueError('observable candidate binding mismatch')
                if r['world_id'] in wanted:public[r['world_id']]=r
        for first in range(0,len(sample),2):
            pair=sample[first:first+2];texts=[public[r['row_id']]['input_text'] for r in pair]
            hs,mask,_=hidden(tokenizer,tower,texts,1415)
            for i,r in enumerate(pair):
                if not torch.equal(hs[23][i,:int(mask[i].sum())].cpu(),r['prefix']):raise ValueError('fresh frozen prefix sample mismatch')
        counts[split]={'all_cached_rows_hash_and_binding_verified':validated,'fresh_model_prefix_rows_exact':len(sample)}
    receipt(OUT/'prefix-fresh-process-replay.json',{'status':'PASS','counts':counts,'original_model_identity':identity,
        'scope':'all cache hashes/bindings; first16 rows per split recomputed exactly, not an exhaustive prefix recomputation',
        'source_sha256':sha(__file__),'protected_evaluation_opened':False})
if __name__=='__main__':main()
