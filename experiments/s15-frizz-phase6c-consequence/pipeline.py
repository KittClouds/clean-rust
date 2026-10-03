"""One prospectively frozen trial and fresh-process verification sequence."""
import sys,subprocess
from common import *
from test_consequence import positive_control


def main():
    setup();lock();control=positive_control()
    if (OUT/'controls.json').exists():
        if control!=read(OUT/'controls.json'):raise ValueError('control reproducibility')
    else:receipt(OUT/'controls.json',control)
    stages=[('prepare.py',[]),('verify_targets.py',[]),('train.py',[]),('evaluate.py',[]),
        ('prepare.py',['--replay']),('evaluate.py',['--replay']),('closeout.py',[]),('closeout.py',['--replay'])]
    for script,args in stages:
        print('START '+script+' '+str(args),flush=True)
        subprocess.run([sys.executable,'-u','-B',str(HERE/script),*args],check=True)
    receipt(OUT/'pipeline-complete.json',{'status':'PASS','evaluation_opened':False})


if __name__=='__main__':main()
