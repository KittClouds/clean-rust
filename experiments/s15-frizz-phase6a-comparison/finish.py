"""Finish successful audit without a user prompt; branch before any new organ."""
import subprocess
import sys
import time
from pathlib import Path
from common import OUT


def main():
    source=Path(__file__).resolve().parent
    while not (OUT/'probe-replay.json').exists():
        logs=(OUT/'stderr-v03.log').read_text() if (OUT/'stderr-v03.log').exists() else ''
        if 'Traceback' in logs:
            raise ValueError('primary audit failed; do not interpret targets')
        time.sleep(15)
    for script in ('verify_states.py','localize.py','closeout.py','verify_seal.py'):
        print('START '+script,flush=True)
        subprocess.run([sys.executable,'-u',str(source/script)],cwd=source,check=True)


if __name__=='__main__':
    main()
