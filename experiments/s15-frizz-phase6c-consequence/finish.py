"""Finish verification/closure without interrupting or refitting the live organ."""
import subprocess,time
from common import *


def main():
    setup();lock()
    while not (OUT/'training-complete.json').exists():time.sleep(3)
    if read(OUT/'training-complete.json')['status']!='PASS':raise ValueError('training incomplete')
    for script,args in [('evaluate.py',[]),('prepare.py',['--replay']),('evaluate.py',['--replay']),
                        ('closeout.py',[]),('closeout.py',['--replay'])]:
        print('START '+script+' '+str(args),flush=True)
        subprocess.run([sys.executable,'-u','-B',str(HERE/script),*args],check=True)
    receipt(OUT/'pipeline-complete.json',{'status':'PASS','evaluation_opened':False})


if __name__=='__main__':main()
