"""Prospective local representations and TRAIN-only fixed diagnostic dose."""
import numpy as np
from common import *
from torch import nn
VIEWS={'local':None,'local_mf24':1,'local_ms24':2,'local_mf18':3,'E_e':-1}
FAMILIES=('linear','mlp')

def width(view):return 32 if view=='E_e' else 4145+(1024 if VIEWS[view] is not None else 0)
def features(abi,d,ix,view,device):
    if view=='E_e':return abi['e'][ix].float().to(device)
    ids=abi['arg_indices'][ix].long();present=(ids>=0).to(device)
    args=d['H']['ent'][ids.clamp_min(0)].float().to(device)
    args=nn.functional.layer_norm(args,(1024,))*present.unsqueeze(-1)
    types=nn.functional.one_hot(abi['types'][ix].long(),9).float().to(device)
    roles=abi['roles'][ix].long();r=nn.functional.one_hot(roles.clamp_min(0),9).float()*(roles>=0).unsqueeze(-1)
    x=torch.cat([types,args.flatten(2),r.to(device).flatten(2),present.float()],-1)
    if VIEWS[view] is not None:
        w=abi['row'][ix,VIEWS[view]].float().to(device)
        x=torch.cat([x,w[:,None].expand(-1,171,-1)],-1)
    return x
def network(view,family):
    n=width(view)
    return nn.Linear(n,1) if family=='linear' else nn.Sequential(nn.Linear(n,64),nn.GELU(),nn.Linear(64,1))
def objective(logits,legal,mask):
    p=mask&legal;n=mask&~legal;pc=p.sum(1);nc=n.sum(1)
    v=((nn.functional.softplus(-logits)*p).sum(1)/pc.clamp_min(1)+
        (nn.functional.softplus(logits)*n).sum(1)/nc.clamp_min(1))/((pc>0).float()+(nc>0).float()).clamp_min(1)
    return v[mask.any(1)].mean()
def predict(model,abi,d,view,device):
    model.eval();out=[];start=time.perf_counter()
    with torch.no_grad():
        for first in range(0,len(abi['row_index']),16):
            ix=torch.arange(first,min(first+16,len(abi['row_index'])))
            out.append(model(features(abi,d,ix,view,device)).squeeze(-1).cpu())
    if device=='cuda':torch.cuda.synchronize()
    return torch.cat(out),time.perf_counter()-start

def assess(logits,abi,t,end,cost):
    result={}
    for name,start in (('primary',0),('paired',1)):
        ix=torch.arange(start,len(logits),2);mask=t['mask'][ix];legal=mask&(t['category'][ix]>=0)&(t['category'][ix]<11)
        types=abi['types'][ix];st=types[torch.arange(len(types)),end['selected'].clamp_min(0)]
        same=mask&(types==st[:,None]);accepted=(logits[ix]>0)&mask
        cell={'full':legality(logits[ix],legal,mask,end['selected'],end['selected_eligible']),
            'same_type':legality(logits[ix],legal,same,end['selected'],end['selected_eligible']),
            'ranking':{'full':rank(cost[ix],accepted,mask,end),'same_type':rank(cost[ix],accepted,same,end)},'slices':{}}
        count=mask.sum(1);lc=legal.sum(1)
        choices=[('count_1_16',count<=16),('count_17_64',(count>16)&(count<=64)),('count_65_plus',count>64),
            ('legal_1',lc==1),('legal_2_4',(lc>=2)&(lc<=4)),('legal_5_plus',lc>=5)]
        choices += [('renderer_'+r,torch.tensor([abi['renderer'][int(i)]==r for i in ix])) for r in sorted(set(abi['renderer']))]
        for label,choose in choices:
            if not choose.any():continue
            e={k:v[choose] for k,v in end.items()}
            cell['slices'][label]={'roots':int(choose.sum()),'reliable':int(choose.sum())>=200,
                'full':legality(logits[ix][choose],legal[choose],mask[choose],e['selected'],e['selected_eligible']),
                'same_type_selection':rank(cost[ix][choose],accepted[choose],same[choose],e)}
        result[name]=cell
    p=(logits>0)&t['mask']
    result['renderer_exact_set_disagreement']=float((p[::2]!=p[1::2]).any(1).float().mean())
    return result

def main(replay=False):
    setup();lock();device='cuda';torch.cuda.set_per_process_memory_fraction(.45)
    data={s:dataset_load(s) for s in ('TRAIN','DEV')}
    abi={s:load(C6/f'{s}-ABI.pt') for s in data};targets={s:load(C6/f'{s}-targets.pt') for s in data}
    end=endpoint(abi['DEV']);cost=load(C6/'DEV-predictions.pt')['trained']['cost'];summaries={}
    folder=OUT/'panel';folder.mkdir(exist_ok=True)
    for view in VIEWS:
        for family in FAMILIES:
            name=view+'-'+family;path=folder/(name+'.pt');meta=path.with_suffix('.json')
            if path.exists() and not replay:
                load(path);summaries[name]=read(folder/(name+'-results.json'));print('VERIFIED COMPLETED '+name,flush=True);continue
            torch.manual_seed(0);model=network(view,family).to(device)
            if replay:
                stored=load(path);initial=stored['initial'];model.load_state_dict(stored['weights'])
            else:
                initial={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
                opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01);start=time.perf_counter();steps=0
                a=abi['TRAIN'];t=targets['TRAIN'];gold=t['mask']&(t['category']>=0)&(t['category']<11)
                for epoch in range(8):
                    perm=torch.randperm(len(a['root_indices']))
                    for first in range(0,len(perm),16):
                        ix=(perm[first:first+16,None]*2+torch.arange(2)).flatten()
                        logits=model(features(a,data['TRAIN'],ix,view,device)).squeeze(-1)
                        loss=objective(logits,gold[ix].to(device),t['mask'][ix].to(device))
                        if not torch.isfinite(loss):raise ValueError('readout nonfinite')
                        opt.zero_grad(set_to_none=True);loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1);opt.step();steps+=1
                torch.cuda.synchronize();fit=time.perf_counter()-start
            trained,secs=predict(model,abi['DEV'],data['DEV'],view,device)
            final_weights={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
            if not replay:train_logits,_=predict(model,abi['TRAIN'],data['TRAIN'],view,device)
            model.load_state_dict(initial);init,_=predict(model,abi['DEV'],data['DEV'],view,device)
            result={'init':assess(init,abi['DEV'],targets['DEV'],end,cost),
                'trained':assess(trained,abi['DEV'],targets['DEV'],end,cost)}
            if replay:
                if not torch.equal(trained,stored['logits']) or not torch.equal(init,stored['init_logits']):raise ValueError('raw logit replay '+name)
                if result!=read(folder/(name+'-results.json')):raise ValueError('raw metrics replay '+name)
            else:
                save(path,{'weights':final_weights,'initial':initial,'logits':trained,'init_logits':init,'TRAIN_logits':train_logits})
                receipt(folder/(name+'-results.json'),result)
                receipt(folder/(name+'-cost.json'),{'fit_seconds':fit,'DEV_seconds':secs,'steps':steps,
                    'parameters':sum(p.numel() for p in model.parameters()),'device':'CUDA FP32 TF32 disabled',
                    'peak_allocated_bytes_process':torch.cuda.max_memory_allocated(),'fixed_epoch':8})
            summaries[name]=result;print(('REPLAY ' if replay else 'FIT ')+name,flush=True)
    if replay:receipt(OUT/'raw-fresh-process-replay.json',{'status':'PASS','arms':list(summaries),'exact_init_and_trained_logits':True})
    else:receipt(OUT/'raw-results.json',summaries)

if __name__=='__main__':main('--replay' in sys.argv)
