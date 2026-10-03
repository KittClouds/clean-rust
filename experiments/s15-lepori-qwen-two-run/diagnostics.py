"""Frozen recoverability analysis. Never optimizes graft/backbone parameters."""
import json

import torch

from common import OUT, receipt, sha, balanced_bce
from dataset import pack
from train import init_model, metric, PRIMARY, PRESERVE


@torch.no_grad()
def representations(model,d):
    model.eval().requires_grad_(False)
    out = {'e':[],'c':[],'cs':[]}
    masks = d['H']['cand_mask'][d['canonical']]
    for st in range(0,len(d['canonical']),128):
        ix = torch.arange(st,min(st+128,len(d['canonical'])),device='cuda')
        H = pack(d,ix)
        s,e,_ = model.graft(H)
        c = model.graft.candidate_states(H)
        cs = torch.cat((c,s[:,None].expand(-1,c.shape[1],-1)),-1)
        for n,x in (('e',e),('c',c),('cs',cs)):
            out[n].append(x[H['cand_mask']].detach())
    return {n:torch.cat(xs) for n,xs in out.items()},masks


def fit_probe(X,y,V,t,pi,mlp,epochs=4,positive_control=False):
    """Fixed final epoch primary; best TRAIN loss secondary; no DEV selection."""
    torch.manual_seed(0)
    net = (torch.nn.Sequential(torch.nn.Linear(X.shape[-1],64),torch.nn.GELU(),
                              torch.nn.Linear(64,1)) if mlp else
           torch.nn.Linear(X.shape[-1],1)).to(X.device)
    opt = torch.optim.AdamW(net.parameters(),lr=1e-3,weight_decay=.01)
    steps = (len(y)+63)//64
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt,steps*epochs)
    history, best, best_state = [], float('inf'), None
    for ep in range(epochs):
        order = torch.randperm(len(y),device=X.device)
        total = 0.
        for st in range(0,len(y),64):
            ix = order[st:st+64]
            l = balanced_bce(net(X[ix]).flatten(),y[ix],pi)
            if not torch.isfinite(l):
                raise RuntimeError('probe instrumentation non-finite loss')
            opt.zero_grad(set_to_none=True);l.backward()
            norm = torch.nn.utils.clip_grad_norm_(net.parameters(),1,error_if_nonfinite=True)
            opt.step();sched.step()
            total += float(l.detach())*len(ix)
        train_loss = total/len(y)
        if train_loss<best:
            best = train_loss;best_state = {n:p.detach().clone() for n,p in net.state_dict().items()}
        history.append({'epoch':ep+1,'train_loss':train_loss})
    with torch.no_grad():
        final = metric(net(V).flatten(),t,pi)
        net.load_state_dict(best_state)
        secondary = metric(net(V).flatten(),t,pi)
    return {'final_epoch':final,'best_train_loss_secondary':secondary,'history':history,
            'epochs':epochs,'positive_control':positive_control,'selection_on_dev':False}


def positive_control(device='cuda'):
    torch.manual_seed(717)
    X,V = torch.randn(2048,8,device=device)*.01,torch.randn(512,8,device=device)*.01
    X[:,0] = torch.where(X[:,0]>0,4.,-4.)
    V[:,0] = torch.where(V[:,0]>0,4.,-4.)
    y,t = (X[:,0]>0).float(),(V[:,0]>0).float()
    controls = {kind:fit_probe(X,y,V,t,float(y.mean()),mlp,positive_control=True)
                for kind,mlp in (('linear',False),('mlp',True))}
    floor = min(x['final_epoch']['balanced_accuracy'] for x in controls.values())
    if floor<.95:
        raise RuntimeError('known-solvable control failed; target negatives uninterpretable')
    return {'result':{'balanced_accuracy':floor},'readout_controls':controls,
            'minimum_balanced_accuracy':.95,'fixture':'label = first feature > 0; margin 4',
            'optimizer_schedule':'identical fit_probe procedure to target arms',
            'protected_data_used':False}


def run_diagnostics(tr,dv,pis):
    folder = OUT/'recoverability'
    if folder.exists():
        raise RuntimeError('diagnostic identity already exists; no implicit refitting')
    folder.mkdir()
    control = positive_control()
    receipt(folder/'positive-control.json',control)
    trained = init_model(tr)
    rec = json.loads((OUT/'phase1/receipt.json').read_text())
    cp = OUT/'phase1'/f'epoch-{rec["best_epoch"]}.pt'
    if sha(cp) != rec['checkpoint_sha256']:
        raise RuntimeError('selected checkpoint identity mismatch')
    trained.load_state_dict(torch.load(cp,weights_only=True))
    X,mask = representations(trained,tr)
    V,v_mask = representations(trained,dv)
    initial = init_model(tr)
    initial.load_state_dict(torch.load(OUT/'initialization.pt',weights_only=True))
    IX,_ = representations(initial,tr)
    IV,_ = representations(initial,dv)
    del trained,initial
    results = {}
    arms = [(r,mlp,PRIMARY,4,False) for r in ('e','c','cs') for mlp in (False,True)]
    arms += [('e',False,PRESERVE,4,False),('e',True,PRESERVE,4,False),
             ('c',True,PRESERVE,4,False),('e',True,PRESERVE,4,True),
             ('e',True,PRIMARY,4,True),('e',True,PRIMARY,12,False),('c',True,PRIMARY,12,False)]
    for rep,mlp,target,epochs,init in arms:
        name = f'{"init" if init else "trained"}-{rep}-{"mlp" if mlp else "linear"}-{target}-{epochs}'
        a,b = (IX[rep],IV[rep]) if init else (X[rep],V[rep])
        y,t = tr['c'][target][mask],dv['c'][target][v_mask]
        result = fit_probe(a,y,b,t,pis[target],mlp,epochs)
        results[name] = result
        receipt(folder/f'{name}.json',result)
        print(json.dumps({'probe':name,'balanced_accuracy':result['final_epoch']['balanced_accuracy']}),flush=True)
    legal_control = results[f'trained-e-mlp-{PRESERVE}-4']['final_epoch']['balanced_accuracy']
    valid = legal_control>.55 and control['result']['balanced_accuracy']>=.95
    deltas = {target:results[f'trained-e-mlp-{target}-4']['final_epoch']['balanced_accuracy']-
                     results[f'init-e-mlp-{target}-4']['final_epoch']['balanced_accuracy']
              for target in (PRIMARY,PRESERVE)}
    receipt(folder/'receipt.json',{'positive_control':control,'arms':results,
            'instrument_valid':valid,'legality_positive_control_floor':.55,
            'initialization_vs_trained_probe_delta':deltas,
            'graft_optimized':False,'backbone_optimized':False,
            'interpretation':'eligible for bounded readout-family interpretation' if valid else
                             'INSTRUMENT_FAILURE: no target negative inference'})
    if not valid:
        raise RuntimeError('recoverability instrument invalid; stop before interpreting target')
