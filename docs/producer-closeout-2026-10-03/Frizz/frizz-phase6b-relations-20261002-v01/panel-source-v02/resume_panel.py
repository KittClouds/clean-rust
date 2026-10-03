"""Freeze engineering-only resume repair; never overwrite finished probe fits."""
import shutil,subprocess,sys,os
from common import HERE,OUT,read,receipt,sha


def main():
    target=OUT/'panel-source-v02';target.mkdir(exist_ok=False)
    names=('common.py','targets.py','probes.py','panel.py','resume_panel.py')
    for name in names:shutil.copy2(HERE/name,target/name)
    old=read(OUT/'PANEL-SPECIFICATION.json')
    old['sources']={n:sha(target/n) for n in names}
    old['engineering_repair']='hash-preserve completed fits; resume missing fits after CUDA illegal access; no dose/labels/features/endpoint change'
    receipt(OUT/'PANEL-SPECIFICATION-v02.json',old)
    environment=dict(os.environ,CUDA_LAUNCH_BLOCKING='1')
    for extra in ([],['--replay']):
        subprocess.run([sys.executable,'-u','-B',str(target/'panel.py'),*extra],check=True,env=environment)


if __name__=='__main__':main()
