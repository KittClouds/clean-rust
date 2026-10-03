"""One low-rank candidate/world compatibility gate; legality only."""
import torch
from torch import nn


class LegalGate(nn.Module):
    def __init__(self):
        super().__init__();self.entity=nn.Linear(1024,32,bias=False);self.world=nn.Linear(1024,16,bias=False)
        self.candidate=nn.Sequential(nn.LayerNorm(465),nn.Linear(465,64),nn.GELU(),nn.LayerNorm(64))
        self.context=nn.Sequential(nn.LayerNorm(230),nn.Linear(230,64),nn.GELU(),nn.LayerNorm(64))
        self.head=nn.Sequential(nn.Linear(192,32),nn.GELU(),nn.Linear(32,1))

    def forward(self,x):
        a=self.entity(nn.functional.layer_norm(x['args'],(1024,)))*x['present'].unsqueeze(-1)
        goal=self.entity(nn.functional.layer_norm(x['goal'],(1024,)))*(x['goal_counts']>0).unsqueeze(-1)
        types=nn.functional.one_hot(x['types'].long(),9).float()
        roles=nn.functional.one_hot(x['roles'].long().clamp_min(0),9).float()*(x['roles']>=0).unsqueeze(-1)
        q=self.candidate(torch.cat([types,a.flatten(2),roles.flatten(2),x['present'].float(),
            nn.functional.layer_norm(x['c'],(256,)),nn.functional.layer_norm(x['e'],(32,))],-1))
        count=x['goal_counts'];flags=torch.cat([count.clamp_max(2)/2,(count==0).float(),(count>1).float()],-1)
        world=self.context(torch.cat([goal.flatten(1),flags,self.world(x['row']).flatten(1),
            nn.functional.layer_norm(x['s'],(64,))],-1))[:,None].expand_as(q)
        return self.head(torch.cat([q,world,q*world],-1)).squeeze(-1)


def loss(logits,legal,mask):
    pos=mask&legal;neg=mask&~legal
    p=pos.sum(1);n=neg.sum(1);classes=(p>0).float()+(n>0).float()
    bce=((nn.functional.softplus(-logits)*pos).sum(1)/p.clamp_min(1)+
         (nn.functional.softplus(logits)*neg).sum(1)/n.clamp_min(1))/classes.clamp_min(1)
    bce=bce[mask.any(1)].mean()
    both=(p>0)&(n>0)
    worst_positive=logits.masked_fill(~pos,float('inf')).min(1).values
    worst_negative=logits.masked_fill(~neg,float('-inf')).max(1).values
    margin=nn.functional.softplus(1+worst_negative[both]-worst_positive[both]).mean() if both.any() else logits.sum()*0
    return {'root_balanced_BCE':bce,'within_root_margin':.1*margin}
