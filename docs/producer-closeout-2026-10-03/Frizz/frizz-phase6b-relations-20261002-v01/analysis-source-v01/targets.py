"""Same-type factor and pair labels; only TRAIN earns probe factors/vocabularies."""
import torch
from common import OUT,P6,read,sha,receipt


def records(split):
    p=OUT/f'{split}-gold.pt'
    if sha(p)!=read(p.with_suffix('.json'))['sha256']:raise ValueError('gold record drift')
    return torch.load(p,mmap=True,weights_only=False)


def build():
    earned=read(OUT/'gold-audit.json')['earned_families_TRAIN_only'];tr=records('TRAIN')
    vocab={}
    for f in earned:
        dim=len(tr[0]['factors'][f][0])
        vocab[f]=[sorted({r['factors'][f][j][k] for r in tr for j in r['same']}) for k in range(dim)]
    for split in ('TRAIN','DEV'):
        base=torch.load(P6/f'{split}-targets.pt',mmap=True,weights_only=False)
        n=len(base['mask']);same=torch.zeros(n,171,dtype=torch.bool)
        ixpairs=torch.zeros(n,170,2,dtype=torch.long);ypairs=torch.zeros(n,170);pmask=torch.zeros(n,170,dtype=torch.bool)
        labels={f:torch.full((n,171,len(vocab[f])),-1,dtype=torch.long) for f in earned}
        difference={f:torch.zeros(n,170,len(vocab[f])) for f in earned}
        for r in records(split):
            i=r['root_index'];s=r['selected'];same[i,r['same']]=True
            for f in earned:
                for j in r['same']:
                    for k,value in enumerate(r['factors'][f][j]):
                        labels[f][i,j,k]=vocab[f][k].index(value) if value in vocab[f][k] else -1
            for k,j in enumerate(x for x in r['same'] if x!=s):
                reverse=(i+k)%2==1;a,b=(j,s) if reverse else (s,j)
                ixpairs[i,k]=torch.tensor([a,b]);ypairs[i,k]=0 if reverse else 1;pmask[i,k]=True
                for f in earned:
                    va=r['factors'][f][a];vb=r['factors'][f][b]
                    difference[f][i,k]=torch.tensor([(x>y)-(x<y) for x,y in zip(va,vb,strict=True)])
        payload={'same_mask':same,'eligible':same.any(1),'pairs':ixpairs,'pair_labels':ypairs,
            'pair_mask':pmask,'labels':labels,'differences':difference,'vocab':vocab,
            'selected':base['selected'],'types':base['types'],'canonical_ids':base['canonical_ids']}
        p=OUT/f'{split}-relations.pt';torch.save(payload,p)
        receipt(p.with_suffix('.json'),{'sha256':sha(p),'eligible_roots':int(payload['eligible'].sum()),
            'pair_roots':int(pmask.any(1).sum()),'same_type_pairs':int(pmask.sum()),
            'factors_earned_from':'TRAIN descriptor audit only','evaluation_opened':False})
    receipt(OUT/'targets-complete.json',{'status':'FIXED_BEFORE_RELATION_PROBE_DEV_SCORING','vocab':vocab})


def load(split):
    p=OUT/f'{split}-relations.pt'
    if sha(p)!=read(p.with_suffix('.json'))['sha256']:raise ValueError('relation target drift')
    return torch.load(p,mmap=True,weights_only=False)


if __name__=='__main__':build()
