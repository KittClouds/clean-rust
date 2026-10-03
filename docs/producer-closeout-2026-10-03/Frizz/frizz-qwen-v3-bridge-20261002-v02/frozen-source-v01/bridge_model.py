"""Mechanism-free dense graft adapted to exhaustive v3 candidates."""
import torch
from torch import nn

from adapter import VOCAB

CANDIDATE_TARGETS = ('candidate_legal', 'candidate_satisfies_goal')
BINARY_TARGETS = ('goal_satisfied', 'solvable')
CORE_TARGETS = ('disposition', 'reason', 'missing_cardinality', 'requestability', 'first_action_type')


class Bridge(nn.Module):
    def __init__(self, classes, width=1024):
        super().__init__()
        self.surfaces = nn.ModuleList([nn.Sequential(nn.LayerNorm(width),
            nn.Linear(width,128), nn.GELU()) for _ in range(6)])
        self.rho_s = nn.Sequential(nn.LayerNorm(768), nn.Linear(768,256), nn.GELU(),
                                   nn.LayerNorm(256), nn.Linear(256,64))
        self.type_emb = nn.Embedding(len(VOCAB),32)
        self.arg_proj = nn.Sequential(nn.LayerNorm(4*width+32), nn.Linear(4*width+32,256),
                                       nn.GELU(), nn.LayerNorm(256))
        self.rho_e = nn.Sequential(nn.Linear(256+64,256), nn.GELU(),
                                   nn.LayerNorm(256), nn.Linear(256,32))
        self.binary = nn.ModuleDict({n:nn.Linear(64,1) for n in BINARY_TARGETS})
        self.core = nn.ModuleDict({n:nn.Linear(64,len(classes[n])) for n in CORE_TARGETS})
        self.candidate = nn.ModuleDict({n:nn.Linear(32,1) for n in CANDIDATE_TARGETS})
        self.action = nn.Linear(32,1)

    def candidate_local(self, H):
        idx = H['cand_ent']
        args = [H['ent'][idx[:,:,slot].clamp_min(0)] *
                (idx[:,:,slot]>=0).unsqueeze(-1) for slot in range(4)]
        return self.arg_proj(torch.cat([*args,self.type_emb(H['cand_type'])],-1))

    def forward(self,H):
        u = torch.stack([p(H['row'][:,i]) for i,p in enumerate(self.surfaces)],1)
        s = self.rho_s(u.flatten(1))
        local = self.candidate_local(H)
        e = self.rho_e(torch.cat([local,s[:,None,:].expand(-1,local.shape[1],-1)],-1))
        e = e * H['cand_mask'].unsqueeze(-1)
        return {'s':s, 'e':e, 'c_local':local, 'u':u,
            'binary':{n:p(s).squeeze(-1) for n,p in self.binary.items()},
            'core':{n:p(s) for n,p in self.core.items()},
            'candidate':{n:p(e).squeeze(-1) for n,p in self.candidate.items()},
            'action':self.action(e).squeeze(-1).masked_fill(~H['cand_mask'],float('-inf'))}
