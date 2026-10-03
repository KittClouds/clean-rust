"""Finish verified bridge recorder automatically; never starts E or opens EVAL."""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path('C:/phoenix-target-overgraph/frizz-qwen-v3-bridge-20261002-v02')


def main():
    here=Path(__file__).resolve().parent
    while not (ROOT/'pipeline-complete.json').exists():
        if (ROOT/'continuation-failure-v02.json').exists():
            raise ValueError('bridge continuation failed; recorder not started')
        time.sleep(15)
    for args in (['recorder_runner.py','--arm','bridge'],
                 ['recorder_runner.py','--arm','bridge','--replay'],['seal_bridge.py']):
        print(json.dumps({'recorder_stage':args,'status':'STARTING'}),flush=True)
        subprocess.run([sys.executable,'-u',str(here/args[0]),*args[1:]],cwd=here,check=True)


if __name__=='__main__':
    main()
