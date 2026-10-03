"""Fresh-process recomputation of the explanatory endpoint recorder."""
import common
from common import *
original_receipt=common.receipt;count=0
def compare(p,v):
    global count
    if v!=read(p):raise ValueError('diagnostic appendix replay mismatch')
    count+=1
common.receipt=compare
try:module('diagnostic_appendix_replay',HERE/'diagnostic-appendix-v01.py')
finally:common.receipt=original_receipt
if count!=1:raise ValueError('missing appendix replay')
original_receipt(OUT/'diagnostic-appendix-replay.json',{'status':'PASS','counts_and_conditional_metrics':'exact',
    'appendix_sha256':sha(OUT/'diagnostic-appendix.json'),'verifier_sha256':sha(Path(__file__)),
    'protected_evaluation_opened':False})
print('DIAGNOSTIC APPENDIX REPLAY PASS',flush=True)
