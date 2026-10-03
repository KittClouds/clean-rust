"""Versioned reporting-only repair; completed model identity unchanged."""
from common import *
old=read(OUT/'SPECIFICATION.json')
old['sources']={p.name:sha(p) for p in HERE.iterdir() if p.suffix in ('.py','.md')}
old['repair']='exact-subset empty-set counter must use subset; no scientific contract changes'
receipt(OUT/'SPECIFICATION-v02.json',old)
receipt(OUT/'ENGINEERING-REPAIR-v02.json',{'failure':'ValueError: exact gate composition mismatch',
    'root_cause':'empty_accepted_sets counted outside declared exact-set subset',
    'original_sources_preserved':'source-v01 and workspace original',
    'scientific_changes':False,'model_retrained':False,'threshold_changed':False,
    'completed_epoch8_sha256':sha(OUT/'epoch-8.pt'),'results_written_before_repair':False,
    'scope':'reporting counter only; new subset regression test'})
