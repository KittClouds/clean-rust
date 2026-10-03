"""One earned surface, resumable FP32 extraction, TRAIN/DEV only."""
import time
from lexi_contract import *

def vectors(model,tokens):
    mask=tokens['attention_mask'];length=mask.sum(1);row=torch.arange(len(length),device=mask.device)
    with torch.inference_mode():
        hidden=model(**tokens,use_cache=False,output_hidden_states=True,return_dict=True).hidden_states[-1]
        final=hidden[row,length-1];mean=(hidden*mask[:,:,None]).sum(1)/length[:,None]
        return torch.cat((final,mean),1).float().cpu().numpy()

def main():
    spec=verify();configure()
    from transformers import AutoTokenizer,AutoModel
    tokenizer=AutoTokenizer.from_pretrained(MODEL,local_files_only=True,trust_remote_code=False)
    if tokenizer.padding_side!='right':raise ValueError('Right padding required')
    model=AutoModel.from_pretrained(MODEL,local_files_only=True,trust_remote_code=False,dtype=torch.float32).eval().cuda()
    for p in model.parameters():p.requires_grad_(False)
    t=time.perf_counter();torch.cuda.reset_peak_memory_stats();parity=False
    for split in ('TRAIN','DEV'):
        if (OUT/f'{split}-EXTRACTION.json').exists():continue
        dest=OUT/'data'/split;texts=[json.loads(l)['input_text'] for l in (dest/'texts.jsonl').open(encoding='utf-8')]
        path=dest/'H.npy';progress=OUT/f'{split}-EXTRACTION-PROGRESS.json'
        state=read(progress) if progress.exists() else {'complete':0,'input_sha256':sha(dest/'texts.jsonl')}
        if state['input_sha256']!=sha(dest/'texts.jsonl'):raise ValueError('Resume input changed')
        start=state['complete'];H=np.lib.format.open_memmap(path,mode='r+' if path.exists() else 'w+',dtype=np.float32,shape=(len(texts),2048))
        for i in range(start,len(texts),4):
            token=tokenizer(texts[i:i+4],padding=True,truncation=False,add_special_tokens=True,return_tensors='pt')
            if token['input_ids'].shape[1]>2048:raise ValueError('Context exceeds frozen extraction limit')
            batch={k:v.cuda() for k,v in token.items()};v=vectors(model,batch)
            if not np.isfinite(v).all():raise ValueError('Nonfinite representations')
            if not parity:
                for j in range(min(2,len(v))):
                    single=tokenizer(texts[i+j],return_tensors='pt',add_special_tokens=True)
                    one=vectors(model,{k:value.cuda() for k,value in single.items()})
                    if np.max(np.abs(v[j]-one[0]))>2e-4:raise ValueError('Batch/solo extraction parity failed')
                parity=True
            H[i:i+len(v)]=v
            if (i//4)%64==0 or i+len(v)==len(texts):
                H.flush();state['complete']=i+len(v)
                temp=progress.with_suffix('.tmp');temp.write_text(json.dumps(state));os.replace(temp,progress)
                print(split,state['complete'],'/',len(texts),'seconds',round(time.perf_counter()-t,1),flush=True)
        del H
        write(OUT/f'{split}-EXTRACTION.json',{'status':'PASS','rows':len(texts),'sha256':sha(path),
          'surface':spec['surface'],'batch_solo_parity':parity,'truncated_rows':0,'model_weights_changed':False,
          'evaluation_files_opened':0,'seconds_so_far':time.perf_counter()-t,
          'peak_cuda_bytes':torch.cuda.max_memory_allocated()})

if __name__=='__main__':main()
