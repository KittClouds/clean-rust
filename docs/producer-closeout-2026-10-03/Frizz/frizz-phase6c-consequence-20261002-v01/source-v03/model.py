"""One candidate-independent consequence sidecar, no comparator or E mutation."""
import math
import torch
from torch import nn


class Consequence(nn.Module):
    def __init__(self):
        super().__init__();self.entity=nn.Linear(1024,32,bias=False);self.world=nn.Linear(1024,16,bias=False)
        self.mlp=nn.Sequential(nn.LayerNorm(823),nn.Linear(823,128),nn.GELU(),nn.Linear(128,64),nn.GELU())
        self.state=nn.Linear(64,4);self.value=nn.Linear(64,1)
        self.first=nn.Parameter(torch.tensor(.5));self.increments=nn.Parameter(torch.full((7,),math.log(math.expm1(1.))))

    def forward(self,x):
        args=nn.functional.layer_norm(x['args'],(1024,))*x['present'].unsqueeze(-1)
        a=self.entity(args);g=self.entity(nn.functional.layer_norm(x['goal'],(1024,)))
        g=g*(x['goal_counts']>0).unsqueeze(-1)
        q=nn.functional.one_hot(x['types'].long(),9).float()
        role=nn.functional.one_hot(x['roles'].long().clamp_min(0),9).float()*(x['roles']>=0).unsqueeze(-1)
        count=x['goal_counts'].float();flags=torch.cat([count.clamp_max(2)/2,(count==0).float(),(count>1).float()],-1)
        global_features=torch.cat([g.flatten(1),flags,self.world(x['row']).flatten(1),
            nn.functional.layer_norm(x['s'],(64,))],-1)
        local=torch.cat([q,a.flatten(2),role.flatten(2),x['present'].float(),
            nn.functional.layer_norm(x['c'],(256,)),nn.functional.layer_norm(x['e'],(32,)),
            (a*g.mean(1)[:,None,None]).flatten(2),global_features[:,None].expand(-1,q.shape[1],-1)],-1)
        h=self.mlp(local);state=self.state(h)
        cuts=torch.cat([self.first.reshape(1),self.first+nn.functional.softplus(self.increments).cumsum(0)])
        ordinal=self.value(h)-cuts
        survival=torch.sigmoid(ordinal);distance=survival.sum(-1)
        p=torch.softmax(state,-1)
        cost=p[:,:,0]*distance+p[:,:,1]*9+p[:,:,2]*10+p[:,:,3]*11
        return {'state':state,'ordinal':ordinal,'distance':distance,'cost':cost}


def state_target(category):
    return torch.where(category<9,0,category-8).long()


def mean_root(values,mask):
    return ((values*mask).sum(1)/mask.sum(1).clamp_min(1))[mask.any(1)].mean()


def losses(o,t,weights):
    mask=t['mask'];y=t['category'];st=state_target(y.clamp_min(0))
    ce=nn.functional.cross_entropy(o['state'].transpose(1,2),st,weight=weights['state'],reduction='none')
    solved=mask&(y<9)&(y>=0);thresholds=torch.arange(8)
    binary=(y[:,:,None]>thresholds).float();pi=weights['ordinal_pi']
    bce=.5*(binary/pi*nn.functional.softplus(-o['ordinal'])+(1-binary)/(1-pi)*nn.functional.softplus(o['ordinal']))
    ordinal=mean_root(bce.mean(-1),solved)
    mae=mean_root(nn.functional.smooth_l1_loss(o['distance'],y.float(),reduction='none')/8,solved)
    pair=t['order_pairs'];r=torch.arange(len(y))[:,None]
    short=o['distance'][r,pair[:,:,0]];long=o['distance'][r,pair[:,:,1]]
    order=mean_root(nn.functional.softplus(1+short-long),t['order_mask']) if t['order_mask'].any() else short.sum()*0
    # Paired renderings are consecutive. Same canonical menu and labels verified.
    diff=(o['cost'][::2]-o['cost'][1::2]).square()/121
    render=mean_root(diff,mask[::2])
    return {'status':mean_root(ce,mask),'ordinal':ordinal,'MAE':.25*mae,'ordering':.25*order,'renderer':.05*render}
