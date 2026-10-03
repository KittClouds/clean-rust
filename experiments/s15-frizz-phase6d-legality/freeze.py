"""Bind complete sources and upstream identities before new DEV scoring."""
import shutil
from common import *
from gate import LegalGate

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    files=[C6/'PHASE6C-SEALED.json',C6/'epoch-8.pt',C6/'DEV-predictions.pt',C6/'results.json',
        C6/'source-v03/model.py',P5/'E/run/epoch-8.pt',P5/'E/recorder-v01/trained-production.pt',
        P6/'DEV-targets.pt',BANK/'PHASE5-HANDOFF-v02.json']
    for split in ('TRAIN','DEV'):
        files.extend(C6/f'{split}-{kind}.pt' for kind in ('ABI','targets'))
        files.append(BRIDGE/f'{split}-dataset.pt')
    for p in list(files):
        if p.suffix=='.pt':files.append(p.with_suffix('.json'))
    # Include every imported frozen helper and canonical simulator implementation.
    files.extend((P5/'E/source').glob('*.py'))
    files.extend(Path('C:/code land/clean-rust/experiments/ff-s15-bank-02/src/bank2').glob('*.py'))
    sources={p.name:sha(p) for p in HERE.iterdir() if p.suffix in ('.py','.md')}
    receipt(OUT/'SPECIFICATION.json',{'sources':sources,'inputs':{str(p):sha(p) for p in files},
        'parameters':sum(p.numel() for p in LegalGate().parameters()),'protected_evaluation_opened':False,
        'qwen_revision':'dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68','final_epoch':8,'threshold_logit':0})
    snapshot=OUT/'source-v01';snapshot.mkdir()
    for name in sources:shutil.copy2(HERE/name,snapshot/name)
    print('DESIGN FROZEN',flush=True)

if __name__=='__main__':main()
