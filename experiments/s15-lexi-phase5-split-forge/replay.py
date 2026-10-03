"""Independent post-run identity replay; no protected population access."""
from lexi_contract import *

def main():
    verify();release=read(OUT/'RELEASE.json')
    for n,h in release['files'].items():
        if sha(OUT/n)!=h:raise ValueError('Artifact replay mismatch '+n)
    bridge=torch.load(OUT/'models'/'BRIDGE'/'best.pt',map_location='cpu',weights_only=True)
    for arm in ['A_DETERMINISTIC','B_STOCHASTIC']:
        state=torch.load(OUT/'models'/arm/'best.pt',map_location='cpu',weights_only=True)
        for k,v in bridge.items():
            if not torch.equal(v,state['seed.'+k]):raise ValueError('Frozen bridge changed '+arm+'/'+k)
    write(OUT/'SEAL-REPLAY.json',{'status':'PASS','independent_process':True,'files_checked':len(release['files']),
      'frozen_bridge_parity':True,'protected_files_opened':0,'release_sha256':sha(OUT/'RELEASE.json')})
    print('INDEPENDENT SEAL REPLAY PASS',flush=True)

if __name__=='__main__':main()
