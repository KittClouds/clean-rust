"""One final full-attention rank4 q/v pilot; immutable prefix and head."""
from common import *
from torch import nn
from panel import network,objective,assess
from extract import load_model,hidden,mention_tokens
CACHE=Path('D:/phoenix-target-overgraph/frizz-phase6e-raw-legality-20261002-v01/prefix23')

class LowRank(nn.Module):
    def __init__(self,base):
        super().__init__();self.base=base;self.base.requires_grad_(False)
        self.a=nn.Parameter(torch.empty(4,base.in_features,device=base.weight.device,dtype=torch.float32))
        self.b=nn.Parameter(torch.zeros(base.out_features,4,device=base.weight.device,dtype=torch.float32))
        nn.init.kaiming_uniform_(self.a,a=5**.5)
    def forward(self,x):
        delta=nn.functional.linear(nn.functional.linear(x.float(),self.a),self.b)
        return self.base(x)+delta.to(x.dtype)

class LatePilot(nn.Module):
    def __init__(self,tower):
        super().__init__();self.layer=tower.layers[23];self.norm=tower.norm;self.rotary=tower.rotary_emb
        self.layer.requires_grad_(False);self.norm.requires_grad_(False);self.rotary.requires_grad_(False)
        if self.layer.block_type!='full_attention':raise ValueError('wrong pilot boundary')
        self.layer.self_attn.q_proj=LowRank(self.layer.self_attn.q_proj)
        self.layer.self_attn.v_proj=LowRank(self.layer.self_attn.v_proj)
        self.head=network('local_mf24','mlp').cuda();self.head.load_state_dict(load(OUT/'panel/local_mf24-mlp.pt')['weights'])
        self.head.requires_grad_(False)
        stats=torch.load(BRIDGE/'surface-stats.pt',weights_only=False)
        self.register_buffer('mean',stats['mean'][1].float().cuda());self.register_buffer('std',stats['std'][1].float().cuda())
    def adapters(self):return {k:v.detach().cpu() for k,v in self.state_dict().items() if k.endswith(('.a','.b'))}
    def set_adapters(self,weights):
        own=self.state_dict()
        for k,v in weights.items():own[k].copy_(v.to(own[k]))
    def tail(self,row):
        x=row['prefix'].cuda().unsqueeze(0);n=x.shape[1];pos=torch.arange(n,device='cuda')[None,None].expand(3,1,-1)
        rope=self.rotary(x,pos)
        causal=torch.full((1,1,n,n),torch.finfo(x.dtype).min,device='cuda',dtype=x.dtype).triu(1)
        y=self.layer(x,position_embeddings=rope,attention_mask=causal,position_ids=pos[0],use_cache=False)
        return self.norm(y)[0]
    def forward(self,row,abi,index):
        final=self.tail(row);ent=[]
        for spans in row['mention_tokens']:
            ent.append(final[spans].float().mean(0).half().float() if spans else final.new_zeros(1024).float())
        ent=torch.stack(ent);ids=row['candidate_entities'].cuda().long();present=ids>=0
        args=ent[ids.clamp_min(0)];args=nn.functional.layer_norm(args,(1024,))*present.unsqueeze(-1)
        types=nn.functional.one_hot(abi['types'][index].cuda().long(),9).float()
        role=abi['roles'][index].cuda().long();roles=nn.functional.one_hot(role.clamp_min(0),9).float()*(role>=0).unsqueeze(-1)
        mf=final.float().mean(0).half().float();mf=((mf-self.mean)/self.std).half().float()
        features=torch.cat([types,args.flatten(1),roles.flatten(1),present.float(),mf.expand(171,-1)],-1)
        return self.head(features).squeeze(-1)

def pilot_lock():
    lock();s=read(OUT/'PILOT-SPECIFICATION.json')
    for name,digest in s['sources'].items():
        if sha(HERE/name)!=digest:raise ValueError('pilot source drift '+name)
    for name,digest in s['inputs'].items():
        if sha(name)!=digest:raise ValueError('pilot input drift '+name)

def load_tower():
    tokenizer,tower,identity=load_model();return tokenizer,tower,identity

def extract_prefix():
    setup();pilot_lock();torch.cuda.set_per_process_memory_fraction(.65)
    tokenizer,tower,identity=load_tower();h=read(BANK/'PHASE5-HANDOFF-v02.json');start=time.perf_counter();counts={};alignment=[]
    for split in ('TRAIN','DEV'):
        abi=load(C6/f'{split}-ABI.pt');d=dataset_load(split)
        wanted={d['row_ids'][int(j)]:i for i,j in enumerate(abi['row_index'])};observations={}
        for name,digest in h['splits'][split]['input_files'].items():
            if sha(BANK/name)!=digest:raise ValueError('public shard drift')
            for r in rows(BANK/name):
                if r['world_id'] in wanted:observations[wanted[r['world_id']]]=r
        if len(observations)!=len(wanted):raise ValueError('public row missing')
        folder=CACHE/split;folder.mkdir(parents=True,exist_ok=True)
        for first in range(0,len(wanted),16):
            p=folder/f'{first:05d}.pt'
            if p.exists():load(p);continue
            result=[]
            for k in range(first,min(first+16,len(wanted)),2):
                group=[observations[i] for i in (k,k+1)]
                hs,mask,offsets=hidden(tokenizer,tower,[r['input_text'] for r in group],1415)
                for q,r in enumerate(group):
                    n=int(mask[q].sum());bindings=r['bindings'];lookup={b['id']:i for i,b in enumerate(bindings)}
                    spans=[mention_tokens(r['input_text'],b['name'],offsets[q]) for b in bindings]
                    args=[[lookup.get(a['args'][key],-1) for key in sorted(a['args'])]+[-1]*(4-len(a['args'])) for a in r['actions']]
                    args += [[-1]*4]*(171-len(args))
                    result.append({'index':k+q,'row_id':r['world_id'],'prefix':hs[23][q,:n].cpu().clone(),
                        'mention_tokens':spans,'candidate_entities':torch.tensor(args,dtype=torch.int16)})
                    # Input extraction qualified: first-root zero-adapter late block parity.
                    if first==0:
                        with torch.no_grad():
                            x=hs[23][q:q+1,:n];pos=torch.arange(n,device='cuda')[None,None].expand(3,1,-1)
                            causal=torch.full((1,1,n,n),torch.finfo(x.dtype).min,device='cuda',dtype=x.dtype).triu(1)
                            y=tower.norm(tower.layers[23](x,position_embeddings=tower.rotary_emb(x,pos),
                                attention_mask=causal,position_ids=pos[0],use_cache=False))
                            reference=hs[24][q:q+1,:n].float();rms=float((y.float()-reference).square().mean().sqrt()/reference.square().mean().sqrt())
                            if rms>.05:raise ValueError('late-boundary identity mismatch')
                            alignment.append({'split':split,'row':k+q,'relative_RMS':rms})
            save(p,result)
            if first%160==0:print('PREFIX '+split+' '+str(first),flush=True)
        counts[split]=len(wanted)
    receipt(OUT/'prefix-extraction.json',{'status':'PASS','rows':counts,'seconds':time.perf_counter()-start,
        'cache_root':str(CACHE),'layer':23,'prefix_frozen':True,'weight_identity':identity,'zero_delta_boundary_parity':alignment,
        'full_text':True,'max_tokens':1415,'evaluation_opened':False})

def iter_cached(split):
    for p in sorted((CACHE/split).glob('*.pt')):
        yield from load(p)

def frozen_parameters(tower,model):
    result={}
    for owner,module in (('Qwen',tower),('readout',model.head)):
        for name,p in module.named_parameters():
            if p.requires_grad:continue
            raw=p.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()
            result[owner+':'+name]=hashlib.sha256(raw).hexdigest()
    return result

def predict_pilot(model,abi,split):
    model.eval();out=[];start=time.perf_counter()
    with torch.no_grad():
        for r in iter_cached(split):out.append(model(r,abi,r['index']).cpu())
    torch.cuda.synchronize();return torch.stack(out),time.perf_counter()-start

def run_pilot(replay=False):
    setup();pilot_lock();torch.cuda.set_per_process_memory_fraction(.65);_,tower,identity=load_tower()
    torch.manual_seed(0);model=LatePilot(tower);folder=OUT/'pilot';folder.mkdir(exist_ok=True)
    before=frozen_parameters(tower,model)
    abi={s:load(C6/f'{s}-ABI.pt') for s in ('TRAIN','DEV')};t=load(C6/'TRAIN-targets.pt')
    if replay:
        saved=load(folder/'epoch-8.pt');model.set_adapters(saved['adapters'])
        logits,secs=predict_pilot(model,abi['DEV'],'DEV')
        if not torch.equal(logits,load(folder/'final-predictions.pt')['logits']):raise ValueError('LoRA fresh-process exact logit replay')
        model.set_adapters(load(folder/'initialization.pt')['adapters']);initial,_=predict_pilot(model,abi['DEV'],'DEV')
        if not torch.equal(initial,load(folder/'initialization.pt')['logits']):raise ValueError('LoRA init replay')
        if before!=frozen_parameters(tower,model):raise ValueError('frozen pilot parameters changed')
        receipt(OUT/'pilot-fresh-process-replay.json',{'status':'PASS','init_and_trained_logits':'exact','evaluation_opened':False,
            'original_parameters_and_readout_unchanged':True,'parameter_tensors_verified':len(before)});return
    init_adapters={k:v.clone() for k,v in model.adapters().items()};initial,initsec=predict_pilot(model,abi['DEV'],'DEV')
    save(folder/'initialization.pt',{'adapters':init_adapters,'logits':initial})
    # No interim DEV contact after initialization; fixed final epoch8 only.
    params=[p for p in model.parameters() if p.requires_grad];opt=torch.optim.AdamW(params,lr=.001,weight_decay=.01)
    gold=t['mask']&(t['category']>=0)&(t['category']<11);steps=0;start=time.perf_counter()
    shards=sorted((CACHE/'TRAIN').glob('*.pt'))
    for epoch in range(1,9):
        model.train();perm=torch.randperm(len(shards));total=0
        for k in perm.tolist():
            group=load(shards[k]);opt.zero_grad(set_to_none=True)
            for r in group:
                i=r['index'];logit=model(r,abi['TRAIN'],i)[None]
                v=objective(logit,gold[i:i+1].cuda(),t['mask'][i:i+1].cuda())/len(group)
                if not torch.isfinite(v):raise ValueError('LoRA nonfinite')
                v.backward();total+=float(v.detach())
            nn.utils.clip_grad_norm_(params,1);opt.step();steps+=1
        save(folder/f'epoch-{epoch}.pt',{'adapters':{k:v.clone() for k,v in model.adapters().items()},'epoch':epoch,
            'optimizer':opt.state_dict(),'rng':torch.get_rng_state(),'CUDA_rng':torch.cuda.get_rng_state()})
        print('PILOT EPOCH '+str(epoch)+' '+str(time.perf_counter()-start),flush=True)
    trained,secs=predict_pilot(model,abi['DEV'],'DEV');save(folder/'final-predictions.pt',{'logits':trained})
    after=frozen_parameters(tower,model)
    if before!=after:raise ValueError('pilot mutated original parameters')
    receipt(OUT/'pilot-frozen-parameter-receipt.json',{'status':'PASS','before':before,'after':after,'exact_unchanged':True})
    # Bind predictions separately; checkpoint remains immutable.
    target=load(C6/'DEV-targets.pt');end=endpoint(abi['DEV']);cost=load(C6/'DEV-predictions.pt')['trained']['cost']
    result={'init':assess(initial,abi['DEV'],target,end,cost),'trained':assess(trained,abi['DEV'],target,end,cost)}
    g=result['trained']['primary']['full'];a=result['init']['primary']['full']
    import numpy as np
    gain=paired_interval(np.array(a['root_exact'],float),np.array(g['root_exact'],float))
    sharp=g['full_exact_set_recovery']>=.50 and gain['delta']>=.10 and gain['ci95'][0]>0 and g['precision']>=.95 and g['recall']>=.90
    ba_gain=g['BA']-a['BA']
    disposition=('FROZEN_ACCESS_LIMIT_BROKEN_BY_SMALL_SUBSTRATE_ADAPTATION' if sharp else
        'RETIRE_MICRO_LORA_CLASSIFICATION_GAIN_WITHOUT_PRECISE_GROUNDING' if ba_gain>=.05 else 'MICRO_LORA_NO_GAIN_AT_THIS_BOUNDARY')
    receipt(OUT/'pilot-results.json',{'results':result,'decision':{'disposition':disposition,'exact_set_gain':gain,
        'BA_gain':ba_gain,'sharp_exact_grounding':sharp,'rank_layer_rescue_sweep':False},'cost':{'fit_seconds':time.perf_counter()-start,
        'DEV_seconds':secs,'init_DEV_seconds':initsec,'trainable_parameters':sum(p.numel() for p in params),
        'peak_cuda_bytes':torch.cuda.max_memory_allocated(),'steps':steps},'evaluation_opened':False})

if __name__=='__main__':
    if '--extract' in sys.argv:extract_prefix()
    else:run_pilot('--replay' in sys.argv)
