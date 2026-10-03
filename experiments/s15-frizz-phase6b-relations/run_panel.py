import subprocess,sys
from pathlib import Path


def main():
    s=Path(__file__).resolve().parent
    for args in (['targets.py'],['panel.py'],['panel.py','--replay']):
        print('START '+str(args),flush=True)
        subprocess.run([sys.executable,'-u',str(s/args[0]),*args[1:]],cwd=s,check=True)


if __name__=='__main__':main()
