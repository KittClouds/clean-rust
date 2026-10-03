"""Exactly two repaired graft-training identities; analysis is a separate program."""
import json
import os
import time

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
import torch
import torch.nn.functional as F

from common import OUT, HERE, OLD, REVISION, Interface, masked_forward, receipt, sha
from common import GLOBAL_GROUPS, CAND_GROUPS, balanced_bce, js_bernoulli
from common import js_categorical, variance_floor_loss
from dataset import load, pack

PRIMARY = 'candidate_satisfies_goal'
PRESERVE = 'candidate_legal'


def losses(g,c,labels_g,labels_c,mask,pis,isolated=False):
    zero = next(iter(c.values())).sum()*0
    cg = [[PRESERVE],[PRIMARY]] if isolated else list(CAND_GROUPS.values())
    E = torch.stack([torch.stack([balanced_bce(c[n][mask],labels_c[n][mask],pis[n])
                                  for n in group]).mean() for group in cg]).mean()
    S = zero if isolated else torch.stack([torch.stack([
        balanced_bce(g[n][:,0],labels_g[n][:,0],pis[n]) for n in group]).mean()
        for group in GLOBAL_GROUPS.values()]).mean()
    return S,E


def prevalence(tr):
    mask = tr['H']['cand_mask'][tr['canonical']]
    return {**{n:float(y[:,0].mean()) for n,y in tr['g'].items()},
            **{n:float(y[mask].mean()) for n,y in tr['c'].items()}}


def pair_loss(model,tr,pair,pis,isolated):
    if tr['split'] != 'TRAIN':
        raise ValueError('differentiable pairs must be TRAIN')
    a,b = pair
    if tr['row_ids'][a].split('@')[0] != tr['row_ids'][b].split('@')[0]:
        raise ValueError('pair candidate identity mismatch')
    ix = torch.tensor([a,b],device=tr['H']['row'].device)
    H = pack(tr,ix,canonical=False)
    _,_,g,c,al,_ = masked_forward(model,H)
    m = H['cand_mask'][0]
    if not torch.equal(m,H['cand_mask'][1]):
        raise ValueError('renderer candidate masks differ')
    groups = [[PRESERVE],[PRIMARY]] if isolated else list(CAND_GROUPS.values())
    E = torch.stack([torch.stack([js_bernoulli(c[n][0,m].sigmoid(),
                    c[n][1,m].sigmoid()).mean() for n in group]).mean()
                    for group in groups]).mean()
    if isolated:
        return E
    S = torch.stack([torch.stack([js_bernoulli(g[n][0,0].sigmoid(),g[n][1,0].sigmoid())
                   for n in group]).mean() for group in GLOBAL_GROUPS.values()]).mean()
    base = tr['row_ids'][a].split('@')[0]
    ci = tr['canonical_lookup'][base]
    A = js_categorical(al[0,m].softmax(-1),al[1,m].softmax(-1)) if tr['action'][ci]>=0 else E*0
    return S+E+A


def metric(logits,y,pi):
    pred = logits>0
    target = y>.5
    pos,neg = target,~target
    rec = float(pred[pos].float().mean()) if pos.any() else 0
    spec = float((~pred[neg]).float().mean()) if neg.any() else 0
    ba = (rec+spec)/2
    return {'balanced_accuracy':ba,'accuracy':float((pred==target).float().mean()),
            'support_positive':int(pos.sum()),'support_negative':int(neg.sum()),
            'train_prevalence':pi,'beats_declared_base_rate_margin':ba>max(pi,1-pi)+.01}


@torch.no_grad()
def evaluate(model,d,pis,isolated=False,outputs=False):
    model.eval()
    globals_,candidates,action,states = [],[],[],[]
    for st in range(0,len(d['canonical']),128):
        ix = torch.arange(st,min(st+128,len(d['canonical'])),device='cuda')
        s,_,g,c,a,_ = masked_forward(model,pack(d,ix))
        states.append(s)
        globals_.append(g); candidates.append(c); action.append(a)
    g = {n:torch.cat([x[n] for x in globals_]) for n in globals_[0]}
    c = {n:torch.cat([x[n] for x in candidates]) for n in candidates[0]}
    a = torch.cat(action)
    m = d['H']['cand_mask'][d['canonical']]
    S,E = losses(g,c,d['g'],d['c'],m,pis,isolated)
    results = {n:metric(c[n][m],d['c'][n][m],pis[n]) for n in
               ([PRESERVE,PRIMARY] if isolated else c)}
    if not isolated:
        results.update({n:metric(g[n][:,0],d['g'][n][:,0],pis[n]) for n in g})
    endpoint = None
    if not isolated:
        valid = d['action']>=0
        pred = a.argmax(1)
        hit = pred==d['action']
        by_type = {}
        for kind in sorted({x['type'] for actions in d['actions'] for x in actions}):
            ix = torch.tensor([i for i,j in enumerate(d['action'].tolist()) if j>=0 and
                               d['actions'][i][j]['type']==kind],device='cuda')
            if len(ix):
                by_type[kind]={'n':len(ix),'accuracy':float(hit[ix].float().mean())}
        endpoint = {'exact_selected_accuracy':float(hit[valid].float().mean()),
                    'n':int(valid.sum()),'by_action_type':by_type,
                    'optimal_set_hit_on_endpoint_rows':float(d['optimal'].gather(1,pred[:,None])
                                                             [valid].float().mean())}
    paired = {}
    counts = {n:[0]*5 for n in ([PRESERVE,PRIMARY] if isolated else list(g)+list(c)+['action'])}
    for x,y in d['pairs']:
        H = pack(d,torch.tensor([x,y],device='cuda'),canonical=False)
        _,_,pg,pc,pa,_ = masked_forward(model,H)
        ci = d['canonical_lookup'][d['row_ids'][x].split('@')[0]]
        for n,vals in counts.items():
            if n=='action':
                truth = d['action'][ci:ci+1]
                if truth[0]<0:
                    continue
                p,q = pa[0].argmax().reshape(1),pa[1].argmax().reshape(1)
            elif n in pg:
                truth = d['g'][n][ci,:1]>.5
                p,q = pg[n][0,:1]>0,pg[n][1,:1]>0
            else:
                valid = H['cand_mask'][0]
                truth = d['c'][n][ci,valid]>.5
                p,q = pc[n][0,valid]>0,pc[n][1,valid]>0
            h,k = p==truth,q==truth
            for j,t in enumerate((h&k,h&~k,~h&k,~h&~k,p!=q)):
                vals[j]+=int(t.sum())
    for n,v in counts.items():
        paired[n] = dict(zip(('both_correct','first_only','second_only','both_wrong','disagreement'),v))
    result = {'heads':results,'endpoint':endpoint,'renderer_paired_correctness':paired,
              'D_s':float(torch.cat(states).std(0,unbiased=False).mean()),
              'J_S':float(S),'J_E':float(E),'criterion':float(E if isolated else .5*(S+E))}
    return (result,g,c,a) if outputs else result


def init_model(tr):
    torch.manual_seed(0)
    model = Interface(tr['H']['row'].shape[-1],64,32,list(tr['g']),list(tr['c']),28).cuda()
    return model


def configure_isolation(model):
    model.heads.requires_grad_(False)
    for n in (PRESERVE,PRIMARY):
        model.heads.c[n].requires_grad_(True)


def run_arm(arm,tr,dv,pis):
    folder = OUT/arm
    if folder.exists():
        raise RuntimeError(f'{arm} already started; no implicit rerun')
    folder.mkdir()
    isolated = arm=='phase1b'
    model = init_model(tr)
    model.load_state_dict(torch.load(OUT/'initialization.pt',weights_only=True))
    if isolated:
        configure_isolation(model)
    active = [p for p in model.parameters() if p.requires_grad]
    receipt(folder/'run-start.json',{'arm':arm,'initialization_sha256':sha(OUT/'initialization.pt'),
            'epochs':8,'seed':0,'optimizer':'AdamW','lr':3e-4,'weight_decay':.01,
            'batch_size':64,'drop_last':True,'clip':1,'renderer_pair_split':'TRAIN',
            'global_action_losses':'OUT' if isolated else 'IN','active_parameters':sum(p.numel() for p in active)})
    sigma = torch.load(OUT/'sigma0.pt',weights_only=True).cuda()
    before = evaluate(model,dv,pis,isolated)
    receipt(folder/'initialization-evaluation.json',before)
    opt = torch.optim.AdamW(active,lr=3e-4,weight_decay=.01)
    n = len(tr['canonical'])
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt,(n//64)*8)
    history = []
    started = time.perf_counter()
    best = float('inf')
    torch.manual_seed(0)  # fixed batch/pair randomization for both arms
    for epoch in range(1,9):
        model.train()
        perm = torch.randperm(n,device='cuda')
        agg = torch.zeros(5,device='cuda')
        for st in range(0,n-63,64):
            ix = perm[st:st+64]
            H = pack(tr,ix)
            s,e,g,c,a,_ = masked_forward(model,H)
            S,E = losses(g,c,{k:x[ix] for k,x in tr['g'].items()},
                         {k:x[ix] for k,x in tr['c'].items()},H['cand_mask'],pis,isolated)
            valid = tr['action'][ix]>=0
            A = F.cross_entropy(a[valid],tr['action'][ix][valid]) if not isolated and valid.any() else E*0
            pair = tr['pairs'][int(torch.randint(len(tr['pairs']),(1,)))]
            P = pair_loss(model,tr,pair,pis,isolated)
            V = variance_floor_loss(s,sigma)
            total = E+(S+.5*A if not isolated else 0)+.25*P+.05*V
            if not torch.isfinite(total):
                raise RuntimeError('non-finite training loss; preserve failed identity')
            opt.zero_grad(set_to_none=True)
            total.backward()
            norm = torch.nn.utils.clip_grad_norm_(active,1,error_if_nonfinite=True)
            opt.step();sched.step()
            agg += torch.stack([S,E,A,P,V]).detach()
        ev = evaluate(model,dv,pis,isolated)
        record = {'epoch':epoch,'seconds':time.perf_counter()-started,
                  'batches':n//64,'mean_terms':(agg/(n//64)).tolist(),
                  'criterion':ev['criterion'],'evaluation':ev}
        history.append(record)
        checkpoint = folder/f'epoch-{epoch}.pt'
        torch.save({k:v.detach().cpu() for k,v in model.state_dict().items()},checkpoint)
        receipt(folder/f'epoch-{epoch}.json',record)
        if ev['criterion']<best:
            best = ev['criterion'];best_epoch = epoch
        print(json.dumps({'arm':arm,'epoch':epoch,'criterion':best,
                         'goal_balacc':ev['heads'][PRIMARY]['balanced_accuracy'],
                         'legal_balacc':ev['heads'][PRESERVE]['balanced_accuracy']}),flush=True)
    selected = folder/f'epoch-{best_epoch}.pt'
    model.load_state_dict(torch.load(selected,weights_only=True))
    final = evaluate(model,dv,pis,isolated)
    deltas = {n:final['heads'][n]['balanced_accuracy']-before['heads'][n]['balanced_accuracy']
              for n in final['heads']}
    receipt(folder/'receipt.json',{'arm':arm,'revision':REVISION,'best_epoch':best_epoch,
            'checkpoint_sha256':sha(selected),'initialization':before,'trained':final,
            'balanced_accuracy_training_delta':deltas,'history':history,
            'protected_test_opened':False,'historical_minicpm_rerun':False,
            'comparison_status':'repaired Qwen vs historical MiniCPM; NOT fully matched'})


def main():
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    tr,dv = load('TRAIN'),load('DEV')
    verification = json.loads((OUT/'dataset-verification.json').read_text())
    if verification['status']!='PASS' or any(verification['splits'][s]['dataset_sha256']!=
             sha(OUT/f'{s}-dataset.pt') for s in ('TRAIN','DEV')):
        raise RuntimeError('independent dataset replay absent or stale')
    for d in (tr,dv):
        d['canonical_lookup'] = {d['row_ids'][int(i)]:j for j,i in enumerate(d['canonical'])}
    pis = prevalence(tr)
    lock = OUT/'training-lock.json'
    if lock.exists():
        raise RuntimeError('training identity exists; resume requires explicit audited implementation')
    receipt(lock,{'source_files':{str(x):sha(x) for x in list(HERE.glob('*.py'))+
            [OLD/'src'/f'{x}.py' for x in ('graft','ontology','objective','data')]},
            'datasets':{s:sha(OUT/f'{s}-dataset.pt') for s in ('TRAIN','DEV')},
            'revision':REVISION,'prevalences':pis,'graft_training_budget':2})
    model = init_model(tr)
    torch.save({k:v.detach().cpu() for k,v in model.state_dict().items()},OUT/'initialization.pt')
    with torch.no_grad():
        states = [model.graft(pack(tr,torch.arange(st,min(st+128,len(tr['canonical'])),
                  device='cuda')))[0] for st in range(0,len(tr['canonical']),128)]
        sigma = torch.cat(states).std(0,unbiased=False).cpu()
    torch.save(sigma,OUT/'sigma0.pt')
    del model,states
    run_arm('phase1',tr,dv,pis)
    from diagnostics import run_diagnostics
    run_diagnostics(tr,dv,pis)
    run_arm('phase1b',tr,dv,pis)


if __name__=='__main__':
    main()
