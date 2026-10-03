from f6 import *

def main():
    torch.set_num_threads(4);spec=read(OUT/'SPEC.json')
    for name,h in read(OUT/'MANIFEST.json')['files'].items():
        if sha(OUT/name)!=h:raise ValueError('Artifact mismatch '+name)
    for name,h in spec['sources'].items():
        if sha(HERE/name)!=h:raise ValueError('Source mismatch')
    for mapping in [spec['parents'],spec['simulator']]:
        for name,h in mapping.items():
            if sha(name)!=h:raise ValueError('Parent mismatch')
    for name,h in read(e6.OUT/'MANIFEST.json')['files'].items():
        if sha(e6.OUT/name)!=h:raise ValueError('Input mismatch')
    a=torch.load(OUT/'model.pt',weights_only=True,map_location='cpu');m=net(spec);m.load_state_dict(a['state']);ts=read(OUT/'THRESHOLDS.json')['values'];checks={}
    for split in ('TRAIN','DEV'):
        z=infer(m,split);old=np.load(OUT/(split+'-logits.npy'))
        delta=float(np.max(np.abs(z-old)))
        if delta!=0:raise ValueError('Inference replay')
        d,rows=derive(split);y,app,types=gold(split);_,_,off=e6.packed(split)
        for i,row in enumerate(rows):
            for j,c in enumerate(row):
                for k,n in enumerate(spec['factor_names']):
                    truth=c['clauses'].get(n,(True,None))[0]
                    if y[off[i]+j,k]!=truth or app[off[i]+j,k]!=(n in c['clauses']):raise ValueError('Primitive replay')
        p,values=compose(spec,z,ts,types)
        if not np.array_equal(p,np.all(values,axis=1)):raise ValueError('Runtime composition')
        # Replay full and selected-type sets independently of recorder.
        _,pp=reconstruct(split,p);yy=d['y']>=.5;mask=d['mask'];same=mask&(d['types']==d['types'][np.arange(len(mask)),d['selected'],None])
        r=read(OUT/'RESULT.json')[split]['sets']
        for name,live in [('full_legal_set',mask),('same_type_legal_set',same)]:
            exact=float((~((pp!=yy)&live).any(1)).mean())
            if exact!=r[name]['exact_set']:raise ValueError('Set replay')
        checks[split]={'logit_max_difference':delta,'rows':len(rows),'roots':len(rows)//2,'candidates':int(mask.sum()),'primitive_replay':True,'exact_set_replay':True}
    write(OUT/'REPLAY.json',{'status':'PASS','fresh_process':True,'checks':checks,'truth_runtime_masks':False,'protected_evaluation_opened':False})
    print('FRESH_REPLAY_PASS',flush=True)
if __name__=='__main__':main()
