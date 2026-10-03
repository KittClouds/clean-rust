"""One fixed local/earlier-layer pass, observable public rows only."""
from d6 import *

def ranges(sp,offsets):
    result=[]
    for start,end in sp:
        matched=np.flatnonzero((offsets[:,1]>start)&(offsets[:,0]<end)&(offsets[:,1]>offsets[:,0]))
        if len(matched):result.append(int(matched[-1]))
    return sorted(set(result))

def main():
    spec=freeze();torch.set_num_threads(4)
    for n,h in spec['model'].items():
        if sha(MODEL/n)!=h:raise ValueError('Model identity changed')
    from transformers import AutoTokenizer,AutoModel
    tok=AutoTokenizer.from_pretrained(MODEL,local_files_only=True,trust_remote_code=False)
    if not tok.is_fast or tok.padding_side!='right':raise ValueError('Offset contract')
    model=AutoModel.from_pretrained(MODEL,local_files_only=True,trust_remote_code=False,dtype=torch.float32).eval().cuda()
    for p in model.parameters():p.requires_grad_(False)
    start=time.perf_counter();torch.cuda.reset_peak_memory_stats()
    for split in ('TRAIN','DEV'):
        folder=OUT/'raw'/split;folder.mkdir(parents=True,exist_ok=True)
        if (folder/'RECEIPT.json').exists():continue
        d=c6.load(split);wanted=set(d['ids'].tolist());public=[p for i,p in enumerate(observable_rows(split)) if i in wanted]
        if [p['world_id'] for p in public]!=[v['id'] for v in d['meta']]:raise ValueError('Row alignment')
        texts=[json.loads(l)['input_text'] for l in (c6.P5/'data'/split/'texts.jsonl').open(encoding='utf-8')]
        for i,p in enumerate(public):
            if p['input_text']!=texts[d['ids'][i]]:raise ValueError('Frozen text changed')
            ids,_=bindings(p);ordinal={v:j+1 for j,v in enumerate(ids)}
            expected=np.zeros_like(d['A'][i])
            for j,a in enumerate(p['actions']):
                expected[j,0]=c6.parent.adapter.VOCAB.index(a['type'])
                for k,key in enumerate(sorted(a['args'])):expected[j,k+1]=ordinal[a['args'][key]]
            if not np.array_equal(expected,d['A'][i]):raise ValueError('Binding ordinal mismatch')
        shapes={'entity':(len(public),65,1024),'presence':(len(public),65),'m4':(len(public),1024)}
        arrays={name:np.lib.format.open_memmap(folder/(name+'.npy'),mode='r+' if (folder/(name+'.npy')).exists() else 'w+',dtype=bool if name=='presence' else np.float32,shape=shape) for name,shape in shapes.items()}
        progress=read(folder/'PROGRESS.json') if (folder/'PROGRESS.json').exists() else {'complete':0,'parity_max':0.,'occurrences':0,'matched_entities':0,'available_entities':0}
        for at in range(progress['complete'],len(public),4):
            rows=public[at:at+4];encoded=tok([p['input_text'] for p in rows],padding=True,truncation=False,return_offsets_mapping=True,return_tensors='pt')
            offsets=encoded.pop('offset_mapping').numpy()
            if encoded['input_ids'].shape[1]>2048:raise ValueError('No truncation allowed')
            token={k:v.cuda() for k,v in encoded.items()}
            with torch.inference_mode():
                states=model(**token,use_cache=False,output_hidden_states=True,return_dict=True).hidden_states
                hidden=states[-1];length=token['attention_mask'].sum(1);rr=torch.arange(len(rows),device='cuda')
                final=hidden[rr,length-1];mean=(hidden*token['attention_mask'][:,:,None]).sum(1)/length[:,None]
                H=torch.cat((final,mean),-1).cpu().numpy()
                delta=float(np.max(np.abs(H-d['H'][at:at+len(rows)])))
                if delta>2e-4:raise ValueError('Inherited extraction parity '+str(delta))
                progress['parity_max']=max(progress['parity_max'],delta)
                arrays['m4'][at:at+len(rows)]=states[model.config.num_hidden_layers-3][rr,length-1].cpu().numpy()
                for i,p in enumerate(rows):
                    _,ss=bindings(p);arrays['entity'][at+i]=0;arrays['presence'][at+i]=False
                    for j,sp in enumerate(ss[1:],1):
                        ends=ranges(sp,offsets[i]);progress['available_entities']+=1
                        if ends:
                            arrays['entity'][at+i,j]=hidden[i,ends].mean(0).cpu().numpy();arrays['presence'][at+i,j]=True
                            progress['matched_entities']+=1;progress['occurrences']+=len(ends)
            progress['complete']=at+len(rows)
            if at%128==0 or progress['complete']==len(public):
                for arr in arrays.values():arr.flush()
                write(folder/'PROGRESS.json',progress);print(split,progress['complete'],len(public),round(time.perf_counter()-start,1),flush=True)
        if not all(np.isfinite(v).all() for k,v in arrays.items() if k!='presence'):raise ValueError('Invalid hidden state')
        write(folder/'RECEIPT.json',{'status':'QUALIFIED','binding_audit':True,'progress':progress,'files':{k+'.npy':sha(folder/(k+'.npy')) for k in arrays},'seconds_so_far':time.perf_counter()-start,'peak_cuda_bytes':torch.cuda.max_memory_allocated(),'protected_contact':False,'input_firewall':'input_text + public bindings + public action arguments only; target labels absent from extraction'})
    print('RAW_EXTRACTION_COMPLETE',flush=True)

if __name__=='__main__':main()
