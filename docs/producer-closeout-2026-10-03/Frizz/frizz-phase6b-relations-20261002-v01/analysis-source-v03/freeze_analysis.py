"""Prospective source snapshot for post-panel diagnostics, no scored choice."""
import shutil
from common import HERE,OUT,receipt,sha


def main():
    names=('common.py','targets.py','probes.py','raw_probe.py','qualification.py','controls.py',
        'verify_gold.py','closeout.py','analysis_runner.py','freeze_analysis.py')
    target=OUT/'analysis-source-v03';target.mkdir(exist_ok=False)
    for n in names:shutil.copy2(HERE/n,target/n)
    receipt(OUT/'ANALYSIS-SOURCE-LOCK-v03.json',{'sources':{n:sha(target/n) for n in names},
        'scope':'prospective conditional raw diagnostics and deterministic closeout; exposed panel source unchanged',
        'evaluation_opened':False})


if __name__=='__main__':main()
