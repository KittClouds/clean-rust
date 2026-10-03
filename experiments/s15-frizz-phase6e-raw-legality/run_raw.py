import os,subprocess,sys
from pathlib import Path
os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8'
here=Path(__file__).resolve().parent
for name,args in [('freeze.py',[]),('panel.py',[]),('panel.py',['--replay']),('errors.py',[]),('localize.py',[])]:
    print('STAGE '+name+' '+' '.join(args),flush=True)
    subprocess.run([sys.executable,str(here/name),*args],check=True)
