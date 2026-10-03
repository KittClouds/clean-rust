import shutil
from common import HERE,OUT,P6,P5,BANK,read,receipt,sha


def main():
    OUT.mkdir(exist_ok=False);s=OUT/'source';s.mkdir()
    for p in HERE.iterdir():
        if p.is_file() and p.suffix in ('.py','.md'):shutil.copy2(p,s/p.name)
    inputs={}
    for p in (P6/'PHASE6A-SEALED-v02.json',P5/'LANE-SEALED.json',BANK/'PHASE5-HANDOFF-v02.json'):
        inputs[str(p)]=sha(p)
    for arm in ('bridge','E'):
        for phenotype in ('init','trained'):
            for split in ('TRAIN','DEV'):
                p=P6/f'{arm}-{phenotype}-{split}.pt';inputs[str(p)]=sha(p)
    contract=read(BANK/'BUILD-CONTRACT.json')
    for n,digest in contract['ancestor_pins'].items():
        if n.endswith(('algebra.py','sim.py','facts.py','requirements.py')):
            if sha(n)!=digest:raise ValueError('semantic source differs from bank pin')
            inputs[n]=digest
    receipt(OUT/'SPECIFICATION.json',{'status':'FROZEN_BEFORE_GOLD_AUDIT',
        'sources':{p.name:sha(p) for p in s.iterdir()},'inputs':inputs,
        'semantic_definitions':'SPECIFICATION.md','evaluation_opened':False,
        'LFM_lane':'out of Frizz scope; left frozen','F':'parked'})


if __name__=='__main__':main()
