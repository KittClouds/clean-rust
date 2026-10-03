"""Restart-safe stage orchestration after the immutable exposed panel."""
import subprocess,sys,time
from common import OUT,HERE,read,receipt,sha


def main():
    for n,h in read(OUT/'ANALYSIS-SOURCE-LOCK-v02.json')['sources'].items():
        if sha(HERE/n)!=h:raise ValueError('analysis source drift '+n)
    while not (OUT/'panel-replay.json').exists():
        if 'Traceback' in (OUT/'panel-v02.stderr.log').read_text(encoding='utf-8',errors='replace'):
            raise ValueError('exposed panel failed; preserve and repair before analysis')
        time.sleep(5)
    for script,replay in (('controls.py',False),('controls.py',True),('qualification.py',False),
                          ('qualification.py',True),('raw_probe.py',False),('raw_probe.py',True),
                          ('closeout.py',False),('closeout.py',True)):
        marker={'controls.py':'controls','qualification.py':'pair-qualification','raw_probe.py':'raw-complete','closeout.py':'PHASE6B-SEALED'}[script]
        if not replay and (OUT/(marker+'.json')).exists():continue
        command=[sys.executable,'-u','-B',str(HERE/script)]+(['--replay'] if replay else [])
        print('START '+str(command),flush=True);subprocess.run(command,check=True)
    receipt(OUT/'analysis-runner-complete.json',{'status':'PASS','evaluation_opened':False})


if __name__=='__main__':main()
