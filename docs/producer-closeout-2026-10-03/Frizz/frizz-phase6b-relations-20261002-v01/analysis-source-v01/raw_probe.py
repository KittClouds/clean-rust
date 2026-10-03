"""Conditional fixed raw-Qwen argument+global diagnostic, no substrate rerun."""
import argparse,time
import torch
from common import OUT,read,receipt,sha,config
from targets import load
from probes import network,offsets,classify_loss,factor_metric
from dataset import load as dataset_load
from runtime import OUT as BRIDGE


def raw(d,ix):
    ids=d['H']['cand_ent'][ix].long();ent=d['H']['ent']
    # Keep the immutable packed entity bank CPU/mmap-resident. Transfer only
    # this microbatch, not both split-wide banks onto the shared GPU.
    present=(ids>=0).cuda().unsqueeze(-1)
    args=ent[ids.clamp_min(0)].float().cuda()*present
    # Same qualified ABI, no latent repair. Per-vector LayerNorm has no learned
    # parameters or DEV-fit moments, avoiding Qwen outlier scales dominating a
    # diagnostic classifier. Global surfaces remain TRAIN-normalized.
    args=torch.nn.functional.layer_norm(args,(1024,))*present
    row=d['H']['row'][ix].float().cuda().flatten(1)
    return torch.cat([args.flatten(2),row[:,None].expand(-1,171,-1)],-1)


def main(replay=False):
    config();tr,dv=load('TRAIN'),load('DEV')
    if not (OUT/'panel-replay.json').exists():raise ValueError('raw branch requires exposed panel verification')
    # A factor is weak if no trained exposed arm has legal-conditioned macro
    # recall >=.80. This selection uses the declared exposed audit, not raw arm
    # shopping; only one raw input ABI and two fixed families are tested.
    weak=[]
    for factor in tr['vocab']:
        values=[]
        for arm in ('bridge','E'):
            for mode in ('c','cs','e'):
                for family in ('linear','mlp'):
                    m=read(OUT/'panel'/arm/'trained'/mode/family/f'factor-{factor}.json')['metric']
                    values.append(m.get('legal_only',m)['mean_component_macro_recall'])
        if max(values)<.80:weak.append(factor)
    if not replay:
        receipt(OUT/'RAW-SPECIFICATION.json',{'weak_factors':weak,'view':'four qualified positional argument vectors + six TRAIN-normalized global Qwen surfaces',
            'width':10240,'families':['linear','64-hidden GELU MLP'],'epochs':4,'seed':0,'lr':.001,'wd':.01,
            'mask':'same-type candidate population; TRAIN only','source_sha256':sha(__file__),
            'normalization':'parameter-free per argument LayerNorm; no DEV fits','evaluation_opened':False})
    if not weak:
        receipt(OUT/('raw-replay.json' if replay else 'raw-complete.json'),{'status':'NOT_NEEDED','weak_factors':[]});return
    datasets={s:dataset_load(s) for s in ('TRAIN','DEV')}
    for factor in weak:
        ranges,count=offsets(tr['vocab'][factor])
        for family in ('linear','mlp'):
            torch.manual_seed(0);model=network(10240,count,family).cuda()
            folder=OUT/'raw';folder.mkdir(exist_ok=True);path=folder/f'{factor}-{family}.pt'
            start=time.perf_counter();steps=0
            if replay:
                saved=torch.load(path,mmap=True,weights_only=False)
                if sha(path)!=read(path.with_suffix('.json'))['sha256']:raise ValueError('raw probe hash drift')
                model.load_state_dict(saved['weights'])
            else:
                opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
                for epoch in range(4):
                    perm=torch.randperm(len(tr['eligible']))
                    for first in range(0,len(perm),64):
                        ix=perm[first:first+64];ix=ix[tr['eligible'][ix]]
                        if not len(ix):continue
                        actual=datasets['TRAIN']['pairs'][ix,0]
                        out=model(raw(datasets['TRAIN'],actual))
                        loss=classify_loss(out,tr['labels'][factor][ix].cuda(),tr['same_mask'][ix].cuda(),ranges)
                        if not torch.isfinite(loss):raise ValueError('raw probe nonfinite loss')
                        opt.zero_grad(set_to_none=True);loss.backward();opt.step();steps+=1
            trainsec=time.perf_counter()-start;model.eval();pred=[];prediction_start=time.perf_counter()
            with torch.no_grad():
                for first in range(0,len(dv['eligible']),16):
                    ix=torch.arange(first,min(first+16,len(dv['eligible'])))
                    # Keep all-row alignment, with microbatches to bound large raw
                    # feature allocation. Raw is frozen; no optimizer/model update.
                    pred.append(model(raw(datasets['DEV'],datasets['DEV']['pairs'][ix,0])).cpu())
            logits=torch.cat(pred);prediction_seconds=time.perf_counter()-prediction_start;metric=factor_metric(logits,dv,factor)
            if factor=='transition_distance' and 'legality' in dv['vocab']:
                one=dv['vocab']['legality'][0].index(1)
                metric['legal_only']=factor_metric(logits,{**dv,'same_mask':dv['same_mask']&(dv['labels']['legality'][:,:,0]==one)},factor)
            if replay:
                if not torch.equal(logits,saved['logits']) or metric!=read(path.with_suffix('.json'))['metric']:
                    raise ValueError('raw frozen surface replay mismatch')
            else:
                torch.save({'weights':{n:x.cpu() for n,x in model.state_dict().items()},'logits':logits},path)
                receipt(path.with_suffix('.json'),{'sha256':sha(path),'metric':metric,'parameters':sum(p.numel() for p in model.parameters()),
                    'training_seconds':trainsec,'DEV_seconds':prediction_seconds,'steps':steps,'peak_cuda_bytes':torch.cuda.max_memory_allocated(),'evaluation_opened':False})
            print('RAW '+factor+' '+family,flush=True)
    receipt(OUT/('raw-replay.json' if replay else 'raw-complete.json'),{'status':'PASS','weak_factors':weak,'evaluation_opened':False})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--replay',action='store_true');a=p.parse_args();main(a.replay)
