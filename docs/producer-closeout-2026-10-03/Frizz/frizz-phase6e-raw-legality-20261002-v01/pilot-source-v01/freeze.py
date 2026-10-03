import shutil
from common import *
from panel import VIEWS,FAMILIES,width
OUT.mkdir(parents=True,exist_ok=False)
files=[D6/'PHASE6D-SEALED.json',D6/'seal-replay.json',D6/'results.json',D6/'epoch-8.pt',
    D6/'source-v02/legal_metrics.py',C6/'epoch-8.pt',C6/'DEV-predictions.pt',C6/'results.json',
    P6/'DEV-targets.pt',BANK/'PHASE5-HANDOFF-v02.json',BRIDGE/'extraction-lock.json',
    P5/'E/run/epoch-8.pt']
for s in ('TRAIN','DEV'):
    files += [C6/f'{s}-ABI.pt',C6/f'{s}-targets.pt',BRIDGE/f'{s}-dataset.pt']
for p in list(files):
    if p.suffix=='.pt':files.append(p.with_suffix('.json'))
files += list((P5/'E/source').glob('*.py'))
files += list(Path('C:/code land/clean-rust/experiments/ff-s15-bank-02/src/bank2').glob('*.py'))
sources={p.name:sha(p) for p in HERE.iterdir() if p.suffix in ('.py','.md')}
receipt(OUT/'RAW-SPECIFICATION.json',{'sources':sources,'inputs':{str(p):sha(p) for p in files},
    'views':VIEWS,'families':FAMILIES,'widths':{v:width(v) for v in VIEWS},'epochs':8,'threshold':0,
    'qualified_surfaces':['mf@24','ms@24','mf@18','final entity mentions@24'],
    'protected_evaluation_opened':False})
folder=OUT/'source-v01';folder.mkdir()
for n in sources:shutil.copy2(HERE/n,folder/n)
print('RAW PANEL FROZEN',flush=True)
