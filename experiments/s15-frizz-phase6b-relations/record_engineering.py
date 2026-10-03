"""Preserved engineering receipt, independent of scientific promotion."""
from common import OUT,receipt,sha,HERE


def main():
    receipt(OUT/'ENGINEERING-RECEIPT-v02.json',{
        'preparation_failure':'str passed to Path-only hash adapter; failed before gold scientific scoring',
        'control_repair':'one unseen DEV distance category made a known-label oracle control fail; only control denominator changed, unknown-as-failure probes unchanged',
        'panel_failure':'CUDA illegal memory access during incomplete readout; source/logs preserved; GPU not reset; other user jobs untouched',
        'panel_resume':'panel-source-v02 uses completed pt/json hashes and skips retraining finished identities; fresh-process full replay still mandatory',
        'analysis_source_v02':'excludes actively written orchestration logs from immutable seal closure; no readout/endpoint change',
        'final_panel_v03':'complete CPU FP32 panel at same family/dose; no mixed GPU/CPU phenotype comparisons; CUDA attempts preserved outside final panel',
        'unit_tests':5,'test_sources':{n:sha(HERE/n) for n in ('test_gold.py','test_probes.py')},
        'evaluation_opened':False})


if __name__=='__main__':main()
