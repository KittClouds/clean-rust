"""Fixed TRAIN factor and same-type pair fits, exact persisted-logit replay."""
import argparse,time
import torch
from common import OUT,HERE,cache,features,config,read,receipt,sha
from targets import load
from probes import network,Pair,offsets,classify_loss,factor_metric,pair_input,pair_metric


def sourcecheck():
    for n,h in read(OUT/'PANEL-SPECIFICATION.json')['sources'].items():
        if sha(HERE/n)!=h:raise ValueError('panel source drift')


def run(replay=False):
    config();sourcecheck();tr,dv=load('TRAIN'),load('DEV')
    for arm in ('bridge','E'):
        for phenotype in ('init','trained'):
            tc=cache(arm,phenotype,'TRAIN') if not replay else None;dc=cache(arm,phenotype,'DEV')
            for mode,dim in (('c',256),('cs',320),('e',32)):
                for family in ('linear','mlp'):
                    folder=OUT/'panel'/arm/phenotype/mode/family
                    if not replay:folder.mkdir(parents=True,exist_ok=False)
                    for factor in tr['vocab']:
                        ranges,out=offsets(tr['vocab'][factor]);name='factor-'+factor
                        fit_or_replay(folder,name,network(dim,out,family).cuda(),tc,dc,tr,dv,mode,
                                      factor=factor,ranges=ranges,replay=replay)
                    for view in ('concat','difference','product'):
                        fit_or_replay(folder,'pair-'+view,Pair(dim*2 if view=='concat' else dim,family,view).cuda(),
                                      tc,dc,tr,dv,mode,view=view,replay=replay)
                    # Gold-factor difference sign is a separate target, not a
                    # selected preference label. Decode from state differences.
                    for factor in tr['vocab']:
                        dimout=len(tr['vocab'][factor])*3
                        fit_or_replay(folder,'delta-'+factor,network(dim,dimout,family).cuda(),tc,dc,tr,dv,
                                      mode,factor=factor,view='difference',delta=True,replay=replay)
                    print(('REPLAY ' if replay else 'FIT ')+str((arm,phenotype,mode,family)),flush=True)
            del tc,dc
    receipt(OUT/('panel-replay.json' if replay else 'panel-complete.json'),{'status':'PASS',
        'evaluation_opened':False,'dose':'four fixed epochs; TRAIN only; no architecture selection'})


def fit_or_replay(folder,name,model,tc,dc,tr,dv,mode,factor=None,ranges=None,view=None,delta=False,replay=False):
    path=folder/f'{name}.pt';torch.manual_seed(0)
    # Reset module initialization under the fixed seed (constructor may precede
    # seed reset). Frozen source makes every arm reproducible independent of order.
    for module in model.modules():
        if hasattr(module,'reset_parameters'):module.reset_parameters()
    started=time.perf_counter();steps=0
    if replay:
        meta=read(path.with_suffix('.json'))
        if sha(path)!=meta['sha256']:raise ValueError('probe weight drift')
        saved=torch.load(path,mmap=True,weights_only=False);model.load_state_dict(saved['weights'])
    else:
        opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
        good=tr['pair_mask'].any(1) if view else tr['eligible']
        for epoch in range(4):
            perm=torch.randperm(len(good))
            for first in range(0,len(perm),64):
                ix=perm[first:first+64];ix=ix[good[ix]]
                if not len(ix):continue
                x=pair_input(tc,tr,mode,view,ix) if view else features(tc,mode,ix)
                output=model(x)
                if delta:
                    y=(tr['differences'][factor][ix].long()+1).cuda();m=tr['pair_mask'][ix].cuda()
                    loss=torch.stack([torch.nn.functional.cross_entropy(output[:,:,k*3:(k+1)*3][m],y[:,:,k][m])
                        for k in range(y.shape[-1])]).mean()
                elif view:
                    m=tr['pair_mask'][ix].cuda();y=tr['pair_labels'][ix].cuda()
                    loss=torch.nn.functional.binary_cross_entropy_with_logits(output[m],y[m])
                else:
                    loss=classify_loss(output,tr['labels'][factor][ix].cuda(),tr['same_mask'][ix].cuda(),ranges)
                if not torch.isfinite(loss):raise ValueError('nonfinite relation probe')
                opt.zero_grad(set_to_none=True);loss.backward();opt.step();steps+=1
    trainseconds=time.perf_counter()-started;model.eval();outputs=[];start=time.perf_counter()
    with torch.no_grad():
        for first in range(0,len(dv['eligible']),64):
            ix=torch.arange(first,min(first+64,len(dv['eligible'])))
            x=pair_input(dc,dv,mode,view,ix) if view else features(dc,mode,ix)
            outputs.append(model(x).cpu())
    logits=torch.cat(outputs);torch.cuda.synchronize();seconds=time.perf_counter()-start
    if delta:
        mask=dv['pair_mask'];y=dv['differences'][factor].long()+1
        components=[]
        for k in range(y.shape[-1]):
            p=logits[:,:,k*3:(k+1)*3].argmax(-1);v=y[:,:,k];rec=[]
            for j in range(3):
                use=mask&(v==j)
                if use.any():rec.append(float((p[use]==j).float().mean()))
            components.append({'accuracy':float((p[mask]==v[mask]).float().mean()),'macro_recall':sum(rec)/len(rec)})
        metric={'components':components,'pairs':int(mask.sum()),'roots':int(mask.any(1).sum())}
    elif view:metric=pair_metric(logits,dv)
    else:
        metric=factor_metric(logits,dv,factor)
        # Planner-factor performance on legal candidates, not inflated by the
        # large INVALID class. Derived target mask only, never a model feature.
        if factor=='transition_distance' and 'legality' in dv['vocab']:
            index=dv['vocab']['legality'][0].index(1)
            legal=dv['same_mask']&(dv['labels']['legality'][:,:,0]==index)
            metric['legal_only']=factor_metric(logits,{**dv,'same_mask':legal},factor)
    if replay:
        if not torch.equal(logits,saved['logits']) or metric!=meta['metric']:raise ValueError('relation probe replay mismatch')
    else:
        torch.save({'weights':{n:x.cpu() for n,x in model.state_dict().items()},'logits':logits},path)
        receipt(path.with_suffix('.json'),{'metric':metric,'sha256':sha(path),'parameters':sum(p.numel() for p in model.parameters()),
            'training_seconds':trainseconds,'DEV_seconds':seconds,'steps':steps,'epochs':4,'evaluation_opened':False})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--replay',action='store_true');a=p.parse_args();run(a.replay)
