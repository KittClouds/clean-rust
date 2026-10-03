"""Bounded local continuation after the already-running extraction process."""
import argparse
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

from runtime import OUT,receipt
from audit_release import sha


def active(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]
    kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:
        return False
    try:
        code=ctypes.c_uint32()
        if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)):
            raise OSError('cannot query extraction process')
        return code.value==259
    finally:
        kernel.CloseHandle(handle)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--extract-pid',type=int,required=True)
    args=parser.parse_args()
    here=Path(__file__).resolve().parent
    source_lock=json.loads((OUT/'pipeline-source-lock.json').read_text())
    receipt(OUT/'pipeline-start.json',{'status':'WAITING_FOR_EXTRACTION',
            'extract_pid':args.extract_pid,'evaluation_opened':False,
            'steps':['dataset.py','train_bridge.py','readouts.py','verify_bridge.py'],
            'automatic_E':False})
    deadline=time.monotonic()+6*3600
    try:
        while not (OUT/'extraction-complete.json').exists():
            if not active(args.extract_pid):
                raise RuntimeError('extraction stopped without completion; preserve attempt')
            if time.monotonic()>deadline:
                raise TimeoutError('extraction continuation timeout')
            time.sleep(5)
        for script in ('dataset.py','train_bridge.py','readouts.py','verify_bridge.py'):
            for name,expected in source_lock['files'].items():
                if sha(here/name)!=expected:
                    raise ValueError('pipeline frozen source changed')
            print(json.dumps({'stage':script,'status':'STARTING'}),flush=True)
            subprocess.run([sys.executable,'-u',str(here/script)],cwd=here,check=True)
        receipt(OUT/'pipeline-complete.json',{'status':'BRIDGE_COMPLETE_VERIFIED',
                'evaluation_opened':False,'E_started':False})
    except Exception as exc:
        receipt(OUT/'pipeline-failure.json',{'status':'STOPPED','error':repr(exc),
                                            'evaluation_opened':False,'E_started':False})
        raise


if __name__=='__main__':
    main()
