import subprocess,sys
from pathlib import Path
here=Path(__file__).resolve().parent
for name,args in [('test_gate.py',[]),('evaluate.py',[]),('evaluate.py',['--replay']),
        ('closeout.py',[]),('closeout.py',['--verify'])]:
    print('REPAIRED STAGE '+name+' '+' '.join(args),flush=True)
    subprocess.run([sys.executable,str(here/name),*args],check=True)
