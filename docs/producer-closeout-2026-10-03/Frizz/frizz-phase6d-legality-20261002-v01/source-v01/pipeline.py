"""Separate-process fit, score, replay and seal; no hidden continuation."""
import subprocess,sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
for script,args in [('test_gate.py',[]),('freeze.py',[]),('verify_targets.py',[]),('train.py',[]),
        ('evaluate.py',[]),('evaluate.py',['--replay']),('closeout.py',[]),('closeout.py',['--verify'])]:
    print('STAGE '+script+' '+' '.join(args),flush=True)
    subprocess.run([sys.executable,str(HERE/script),*args],check=True)
print('PHASE6D COMPLETE',flush=True)
