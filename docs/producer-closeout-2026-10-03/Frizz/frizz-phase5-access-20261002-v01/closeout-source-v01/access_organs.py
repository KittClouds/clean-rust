"""One typed gated E organ; sparse alternative is defined only if E is retired."""
import torch
from torch import nn
from bridge_model import Bridge
from context_inputs import ROLES


class TypedGate(nn.Module):
    def __init__(self,width=1024):
        super().__init__()
        self.entity=nn.Linear(width,64,bias=False)
        self.role=nn.Embedding(len(ROLES),64)
        self.q=nn.Linear(32,64,bias=False)
        self.r_norm=nn.LayerNorm(64)
        self.goal=nn.Linear(width,64,bias=False)
        self.g=nn.Sequential(nn.LayerNorm(134),nn.Linear(134,64),nn.GELU(),nn.LayerNorm(64))
        self.w=nn.Linear(64,64)
        self.gate=nn.Linear(192,64)
        self.interaction=nn.Sequential(nn.Linear(128,64),nn.GELU())
        self.output=nn.Linear(64,32)
        nn.init.zeros_(self.output.weight);nn.init.zeros_(self.output.bias)

    def forward(self,H,q,s):
        indices=H['cand_ent'];roles=H['role_ids'];present=roles>=0
        entities=H['ent'][indices.clamp_min(0)]
        entity=self.entity(entities)*(indices>=0).unsqueeze(-1)
        # A present role with an unobserved entity retains the role coordinate,
        # but no latent name is reconstructed. Padding contributes nothing.
        typed=(entity+self.role(roles.clamp_min(0)))*present.unsqueeze(-1)
        r=self.r_norm(typed.sum(-2)/present.sum(-1).clamp_min(1).sqrt().unsqueeze(-1)+self.q(q))
        counts=H['goal_counts']
        flags=torch.cat([counts.clamp_max(2)/2,(counts==0).float(),(counts>1).float()],-1)
        g=self.g(torch.cat([self.goal(H['goal_vectors']).flatten(1),flags],-1))
        w=self.w(s);g=g[:,None,:].expand_as(r);w=w[:,None,:].expand_as(r)
        gate=torch.sigmoid(self.gate(torch.cat([r,g,w],-1)))
        relation=self.interaction(torch.cat([r*g,r*w],-1))
        return self.output(gate*relation)*H['cand_mask'].unsqueeze(-1)


class Structured(Bridge):
    def __init__(self,classes,width=1024):
        super().__init__(classes,width);self.organ=TypedGate(width)

    def forward(self,H):
        o=super().forward(H)
        e=(o['e']+self.organ(H,self.type_emb(H['cand_type']),o['s']))*H['cand_mask'].unsqueeze(-1)
        o['e']=e
        o['candidate']={n:p(e).squeeze(-1) for n,p in self.candidate.items()}
        o['action']=self.action(e).squeeze(-1).masked_fill(~H['cand_mask'],float('-inf'))
        return o


class Sparse(Bridge):
    def __init__(self,*args,**kwargs):
        raise ValueError('F is not defined or authorized by an E-failure disposition yet')
