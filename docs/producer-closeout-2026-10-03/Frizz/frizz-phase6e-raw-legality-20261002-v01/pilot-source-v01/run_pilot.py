import os,subprocess,sys
from pathlib import Path
os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8'
here=Path(__file__).resolve().parent
for name,args in [('test_access.py',[]),('freeze_pilot.py',[]),('late_access.py',['--extract']),('late_access.py',[]),('late_access.py',['--replay'])]:
    print('EARNED PILOT STAGE '+name+' '+' '.join(args),flush=True)
    subprocess.run([sys.executable,str(here/name),*args],check=True)
