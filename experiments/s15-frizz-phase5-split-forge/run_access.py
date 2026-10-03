"""Carry one prospectively frozen access family through training and disposition."""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def main(arm):
    here=Path(__file__).resolve().parent
    for args in (['train_access.py','--arm',arm],['recorder_runner.py','--arm',arm],
                 ['recorder_runner.py','--arm',arm,'--replay'],['axis_readouts.py','--arm',arm],
                 ['disposition_access.py','--arm',arm]):
        print(json.dumps({'arm':arm,'stage':args[0],'status':'STARTING'}),flush=True)
        subprocess.run([sys.executable,'-u',str(here/args[0]),*args[1:]],cwd=here,check=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--arm',choices=['E','F'],required=True)
    main(parser.parse_args().arm)
