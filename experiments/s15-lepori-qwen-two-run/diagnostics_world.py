"""Versioned repair: inherited bs=64 WORLDS, not 64 flattened candidates.

The earlier candidate-batched analysis is preserved, explicitly unmatched, and
never used to select a readout or checkpoint. Graft/backbone stay frozen here.
"""
import json

import torch

from common import OUT, HERE, receipt, sha, balanced_bce
from dataset import pack
from train import init_model, metric, PRIMARY, PRESERVE


@torch.no_grad()
def representations(model,d):
    model.eval().requires_grad_(False)
    out = {'e':[],'c':[],'cs':[]}
    for st in range(0,len(d['canonical']),128):
        ix = torch.arange(st,min(st+128,len(d['canonical'])),device='cuda')
        H = pack(d,ix)
        s,e,_ = model.graft(H)
        c = model.graft.candidate_states(H)
        # Match the inherited frozen representation cache's FP16 storage.
        sh,ch,eh = s.half(),c.half(),e.half()
        cs = torch.cat((ch,sh[:,None].expand(-1,ch.shape[1],-1)),-1)
        for n,x in (('e',eh),('c',ch),('cs',cs)):
            out[n].append(x.detach())
    return {n:torch.cat(xs) for n,xs in out.items()}


def readout(width,mlp,device):
    torch.manual_seed(0)
    return (torch.nn.Sequential(torch.nn.Linear(width,64),torch.nn.GELU(),
                               torch.nn.Linear(64,1)) if mlp else
            torch.nn.Linear(width,1)).to(device)


@torch.no_grad()
def train_subsample_loss(net,X,y,m,pi):
    # Same fixed 4096-world subsample as the inherited implementation.
    sel = torch.linspace(0,len(X)-1,min(4096,len(X))).long().to(X.device)
    total, count = 0.,0
    for st in range(0,len(sel),128):
        ix = sel[st:st+128]
        mask = m[ix]
        loss = balanced_bce(net(X[ix].float()).squeeze(-1)[mask],y[ix][mask],pi)
        n = int(mask.sum())
        total += float(loss)*n;count+=n
    return total/count


@torch.no_grad()
def score(net,X,y,m,pi):
    parts = [net(X[st:st+128].float()).squeeze(-1) for st in range(0,len(X),128)]
    return metric(torch.cat(parts)[m],y[m],pi)


def fit_world(X,y,m,V,t,vm,pi,mlp,epochs,folder,name):
    net = readout(X.shape[-1],mlp,X.device)
    opt = torch.optim.AdamW(net.parameters(),lr=1e-3,weight_decay=.01)
    steps = len(X)//64
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt,steps*epochs)
    history,best,best_state,best_epoch = [],float('inf'),None,0
    for ep in range(1,epochs+1):
        net.train()
        perm = torch.randperm(len(X),device=X.device)
        for st in range(0,len(X)-63,64):
            ix = perm[st:st+64]
            valid = m[ix]
            l = balanced_bce(net(X[ix].float()).squeeze(-1)[valid],y[ix][valid],pi)
            if not torch.isfinite(l):
                raise RuntimeError('world-probe instrument failure: nonfinite loss')
            opt.zero_grad(set_to_none=True);l.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(),1,error_if_nonfinite=True)
            opt.step();sched.step()
        net.eval()
        loss = train_subsample_loss(net,X,y,m,pi)
        if loss<best:
            best,best_epoch = loss,ep
            best_state = {n:p.detach().clone() for n,p in net.state_dict().items()}
        history.append({'epoch':ep,'fixed_train_subsample_loss':loss})
    final = score(net,V,t,vm,pi)
    fp = folder/f'{name}-final.pt'
    torch.save({n:p.detach().cpu() for n,p in net.state_dict().items()},fp)
    net.load_state_dict(best_state)
    secondary = score(net,V,t,vm,pi)
    bp = folder/f'{name}-best-train.pt'
    torch.save({n:p.detach().cpu() for n,p in net.state_dict().items()},bp)
    result = {'final_epoch':final,'best_train_loss_secondary':secondary,'history':history,
        'best_train_epoch':best_epoch,'epochs':epochs,'optimizer_steps':steps*epochs,
        'batch_size':64,'batch_unit':'WORLDS','drop_last':True,'cached_dtype':'FP16',
        'selection_on_dev':False,'final_readout_sha256':sha(fp),'best_train_readout_sha256':sha(bp)}
    receipt(folder/f'{name}.json',result)
    return result


def positive_controls(folder,device='cuda'):
    torch.manual_seed(717)
    X,V = torch.randn(2048,4,8,device=device)*.01,torch.randn(512,4,8,device=device)*.01
    X[:,:,0] = torch.where(X[:,:,0]>0,4.,-4.)
    V[:,:,0] = torch.where(V[:,:,0]>0,4.,-4.)
    y,t = (X[:,:,0]>0).float(),(V[:,:,0]>0).float()
    m,vm = torch.ones_like(y,dtype=torch.bool),torch.ones_like(t,dtype=torch.bool)
    results = {kind:fit_world(X.half(),y,m,V.half(),t,vm,float(y.mean()),mlp,4,folder,
                             'positive-control-'+kind) for kind,mlp in (('linear',False),('mlp',True))}
    if min(x['final_epoch']['balanced_accuracy'] for x in results.values())<.95:
        raise RuntimeError('known-solvable world-probe positive control failed')
    return results


def run_world_diagnostics(tr,dv,pis):
    folder = OUT/'recoverability-world-v02'
    if folder.exists():
        raise RuntimeError('world-diagnostic identity exists; no implicit refit')
    folder.mkdir()
    controls = positive_controls(folder)
    trained = init_model(tr)
    rec = json.loads((OUT/'phase1/receipt.json').read_text())
    cp = OUT/'phase1'/f'epoch-{rec["best_epoch"]}.pt'
    if sha(cp)!=rec['checkpoint_sha256']:
        raise RuntimeError('selected graft checkpoint identity mismatch')
    trained.load_state_dict(torch.load(cp,weights_only=True))
    X,V = representations(trained,tr),representations(trained,dv)
    initial = init_model(tr)
    initial.load_state_dict(torch.load(OUT/'initialization.pt',weights_only=True))
    IX,IV = representations(initial,tr),representations(initial,dv)
    del trained,initial
    masks = tr['H']['cand_mask'][tr['canonical']],dv['H']['cand_mask'][dv['canonical']]
    arms = [(r,mlp,PRIMARY,4,False) for r in ('e','c','cs') for mlp in (False,True)]
    arms += [('e',False,PRESERVE,4,False),('e',True,PRESERVE,4,False),
             ('c',True,PRESERVE,4,False),('e',True,PRESERVE,4,True),
             ('e',True,PRIMARY,4,True),('e',True,PRIMARY,12,False),('c',True,PRIMARY,12,False)]
    results = {}
    for rep,mlp,target,epochs,init in arms:
        name = f'{"init" if init else "trained"}-{rep}-{"mlp" if mlp else "linear"}-{target}-{epochs}'
        a,b = (IX[rep],IV[rep]) if init else (X[rep],V[rep])
        result = fit_world(a,tr['c'][target],masks[0],b,dv['c'][target],masks[1],pis[target],
                           mlp,epochs,folder,name)
        results[name] = result
        print(json.dumps({'world_probe':name,'balanced_accuracy':result['final_epoch']['balanced_accuracy']}),flush=True)
    legal = results[f'trained-e-mlp-{PRESERVE}-4']['final_epoch']['balanced_accuracy']
    valid = legal>.55
    deltas = {t:results[f'trained-e-mlp-{t}-4']['final_epoch']['balanced_accuracy']-
                results[f'init-e-mlp-{t}-4']['final_epoch']['balanced_accuracy'] for t in (PRIMARY,PRESERVE)}
    receipt(folder/'receipt.json',{'instrument_valid':valid,'arms':results,
        'positive_controls':controls,'initialization_vs_trained_probe_delta':deltas,
        'batch_unit':'WORLDS','graft_optimized':False,'backbone_optimized':False,
        'source_sha256':sha(HERE/'diagnostics_world.py'),
        'unmatched_candidate_batched_analysis':'preserved in recoverability; excluded from primary comparison'})
    if not valid:
        raise RuntimeError('world-probe legality control failed; no target negative interpretation')
