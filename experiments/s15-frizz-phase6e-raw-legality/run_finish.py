import os,subprocess,sys
from pathlib import Path
os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8'
here=Path(__file__).resolve().parent
for name,args in [('verify_prefix.py',[]),('finish_audit.py',['--metrics']),('finish_audit.py',['--supports']),
        ('finish_audit.py',[]),('finish_audit.py',['--verify-seal'])]:
    print('FINAL STAGE '+name+' '+' '.join(args),flush=True)
    subprocess.run([sys.executable,str(here/name),*args],check=True)
print('PHASE6E SEALED AND VERIFIED',flush=True)
