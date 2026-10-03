"""Bound frozen-state audit through fit and exact replay; no automatic organ."""
import subprocess
import sys
from pathlib import Path


def main():
    source=Path(__file__).resolve().parent
    for args in (['prepare.py'],['panel.py'],['panel.py','--replay']):
        print('START '+str(args),flush=True)
        subprocess.run([sys.executable,'-u',str(source/args[0]),*args[1:]],cwd=source,check=True)


if __name__=='__main__':
    main()
