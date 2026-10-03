"""Reconstruct missing recurrent depths from frozen graft only; compact eligible rows."""
import time
from p6_contract import *

@torch.no_grad()
def build():
    if (OUT/'CACHE-RECEIPT.json').exists():return read(OUT/'CACHE-RECEIPT.json')
    configure();verify()
    inventory=read(P5_FINAL/'INPUT-INVENTORY.json')
    lookup={row['relative_path']:row['sha256'] for row in inventory['files']}
    consumed={}
    paths=[P5/'PHASE5-SPEC.json']+[P5/'models'/arm/'best.pt' for arm in ['BRIDGE','A_DETERMINISTIC']]
    for split in ['TRAIN','DEV']:
        paths += [P5/'data'/split/(key+'.npy') for key in ['H','A','mask','action','optimal']]
        paths += [P5/'data'/split/'metadata.json']
        paths += [P5/'states'/arm/(split+'-'+kind+'.npy') for arm in ['BRIDGE','A_DETERMINISTIC'] for kind in ['s','e']]
    paths += list((P5/'predictions'/'A_DETERMINISTIC').glob('*.npz'))
    for path in paths:
        key=path.relative_to(P5).as_posix();digest=sha(path)
        if digest!=lookup[key]:raise ValueError('Sealed parent input changed '+key)
        consumed[key]=digest
    seed=new_bridge().cuda();seed.load_state_dict(torch.load(P5/'models'/'BRIDGE'/'best.pt',weights_only=True,map_location='cpu'))
    model=RecurrentCausalGraft(seed).cuda();model.load_state_dict(torch.load(P5/'models'/'A_DETERMINISTIC'/'best.pt',weights_only=True,map_location='cpu'))
    model.eval()
    for p in model.parameters():p.requires_grad_(False)
    start=time.perf_counter();torch.cuda.reset_peak_memory_stats();splits={}
    for split in ['TRAIN','DEV']:
        arrays,meta,ids=load_split(split);folder=OUT/'cache'/split;folder.mkdir(parents=True,exist_ok=True)
        n=len(ids);dest=[]
        for depth in range(5):
            dest.append({
              's':np.lib.format.open_memmap(folder/f'T{depth}-s.npy',mode='w+',dtype=np.float32,shape=(n,64)),
              'e':np.lib.format.open_memmap(folder/f'T{depth}-e.npy',mode='w+',dtype=np.float32,shape=(n,171,64)),
              'production':np.lib.format.open_memmap(folder/f'T{depth}-production.npy',mode='w+',dtype=np.float32,shape=(n,171))})
        parent={d:{kind:np.load(P5/'states'/arm/(split+'-'+kind+'.npy'),mmap_mode='r') for kind in ['s','e']}
          for d,arm in [(0,'BRIDGE'),(4,'A_DETERMINISTIC')]}
        production={d:np.load(P5/'predictions'/'A_DETERMINISTIC'/f'{SEED}-T{d}.npz')['action'] for d in range(5)} if split=='DEV' else {}
        position=np.full(len(meta),-1,np.int64);position[ids]=np.arange(n);checks=0
        for at in range(0,len(meta),64):
            rowids=np.arange(at,min(at+64,len(meta)))
            batch={'H':torch.tensor(np.array(arrays['H'][rowids]),device='cuda'),
              'A':torch.tensor(np.array(arrays['A'][rowids]),device='cuda',dtype=torch.long),
              'candidate_mask':torch.tensor(np.array(arrays['mask'][rowids]),device='cuda')}
            outputs,_=model.forward_states(batch)
            eligible=position[rowids]>=0;compact=position[rowids[eligible]]
            for depth,out in enumerate(outputs):
                s=out['s'].cpu().numpy();e=out['e'].cpu().numpy();scores=out['action_logits'].cpu().numpy()
                if depth in parent:
                    for kind,value in [('s',s),('e',e)]:
                        if not np.array_equal(value,parent[depth][kind][rowids]):
                            delta=float(np.abs(value-parent[depth][kind][rowids]).max())
                            raise ValueError(f'Frozen cache replay differs {split}/T{depth}/{kind}: {delta}')
                        checks+=1
                if split=='DEV' and not np.array_equal(scores.argmax(1),production[depth][rowids]):
                    raise ValueError(f'Production endpoint parity failed DEV/T{depth}')
                if len(compact):
                    dest[depth]['s'][compact]=s[eligible];dest[depth]['e'][compact]=e[eligible]
                    # Keep finite raw scalar scores; canonical mask is applied by ranking metrics.
                    dest[depth]['production'][compact]=scores[eligible]
            if (at//64)%50==0:print(f'CACHE {split} {at+len(rowids)}/{len(meta)}',flush=True)
        for values in dest:
            for value in values.values():value.flush()
        for key,value in {'ids':ids,'mask':arrays['mask'][ids], 'types':arrays['A'][ids,:,0],
            'selected':arrays['action'][ids],'optimal':arrays['optimal'][ids]}.items():np.save(folder/(key+'.npy'),value)
        write(folder/'metadata.json',[meta[i] for i in ids])
        empty=~arrays['optimal'].any(1)
        singleton=np.all(arrays['optimal'][ids].sum(1)==1)
        splits[split]={'full_rows':len(meta),'eligible_rows':n,'eligible_roots':n//2,
            'empty_optimal_rows':int(empty.sum()),'empty_optimal_roots':int(empty.sum())//2,
            'max_candidates_full':int(arrays['mask'].sum(1).max()),'max_candidates_eligible':int(arrays['mask'][ids].sum(1).max()),
            'terminal_and_bridge_cache_exact_checks':checks,'optimal_singleton_selected_identity':bool(singleton),
            'DEV_production_argmax_parity':True if split=='DEV' else None}
    verify()
    result={'status':'PASS','splits':splits,'seconds':time.perf_counter()-start,
       'peak_cuda_bytes':torch.cuda.max_memory_allocated(),'backbone_forward_passes':0,'backbone_weights_opened':False,
       'frozen_graft_weights_changed':False,'protected_files_opened':0,'consumed_parent_files':consumed,
       'cache_files':{p.relative_to(OUT).as_posix():sha(p) for p in (OUT/'cache').rglob('*') if p.is_file()}}
    write(OUT/'CACHE-RECEIPT.json',result);print('CACHE COMPLETE',json.dumps(splits),flush=True);return result

if __name__=='__main__':build()
