"""Versioned assembly repair continuation; no extractor or bridge-contract change."""
import json
import subprocess
import sys
from pathlib import Path
from runtime import OUT,receipt
from audit_release import sha


def main():
    here=Path(__file__).resolve().parent
    lock=json.loads((OUT/'pipeline-source-lock-v02.json').read_text())
    receipt(OUT/'continuation-start-v02.json',{'reason':'unbound observable argument slots',
            'predecessor':'pipeline-failure.json','training_started_before_repair':False,
            'extractor_changed':False,'corpus_changed':False,'evaluation_opened':False})
    try:
        for script in ('dataset.py','train_bridge.py','readouts.py','verify_bridge.py'):
            if any(sha(here/name)!=expected for name,expected in lock['files'].items()):
                raise ValueError('continuation source drift')
            print(json.dumps({'stage':script,'status':'STARTING'}),flush=True)
            subprocess.run([sys.executable,'-u',str(here/script)],cwd=here,check=True)
        receipt(OUT/'pipeline-complete.json',{'status':'BRIDGE_COMPLETE_VERIFIED',
                'continuation':'v02','evaluation_opened':False,'E_started':False})
    except Exception as exc:
        receipt(OUT/'continuation-failure-v02.json',{'error':repr(exc),'evaluation_opened':False})
        raise


if __name__=='__main__':
    main()
