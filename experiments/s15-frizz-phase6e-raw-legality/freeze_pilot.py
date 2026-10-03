"""Earned rank4 pilot boundary; freeze after complete raw replay/localization."""
import shutil
from common import *
lock();localization=read(OUT/'RAW-LOCALIZATION.json')
if not localization['micro_LoRA_earned']:raise ValueError('pilot not earned')
if read(OUT/'raw-fresh-process-replay.json')['status']!='PASS':raise ValueError('raw replay required')
files=[OUT/'RAW-LOCALIZATION.json',OUT/'raw-results.json',OUT/'raw-fresh-process-replay.json',
    OUT/'TRAIN-error-families.json',OUT/'panel/local_mf24-mlp.pt',BRIDGE/'surface-stats.pt',
    P5/'E/source/extract.py',P5/'E/source/runtime.py']
model_lock=read(BRIDGE/'extraction-lock.json')
for n,h in model_lock['model_files'].items():
    if sha(MODEL/n)!=h:raise ValueError('original model file drift '+n)
    files.append(MODEL/n)
sources={p.name:sha(p) for p in HERE.iterdir() if p.suffix in ('.py','.md')}
receipt(OUT/'PILOT-SPECIFICATION.json',{'sources':sources,'inputs':{str(p):sha(p) for p in files},
    'rank':4,'alpha':4,'scale':1,'boundary':'language_model.layers.23.self_attn.q_proj and v_proj',
    'justification':'final qualified entity/context surfaces terminate at last full-attention block; smallest late boundary affecting both, no new raw surface search',
    'q_proj_caveat':'Qwen q_proj jointly supplies query and output-gate coordinates; both receive rank4 delta',
    'head':'frozen already-fitted local_mf24 64-unit MLP; no new readout fit',
    'epochs':8,'seed':0,'fixed_endpoint':8,'threshold_logit':0,'AdamW_lr':.001,'weight_decay':.01,'clip':1,
    'batch':'8 canonical roots /16 paired rows, fixed prefix shards randomly ordered each epoch; tail rows accumulate equal BCE gradients',
    'only_trainable_parameters':'rank4 q/v adapters, zero-B initialization; all original Qwen parameters/head frozen',
    'target':'canonical binary legality only, root/class-balanced BCE','normalization':'same frozen TRAIN surface moments and positional role contract',
    'prefix_cache':'hidden input immediately before layer23, public-only full-text; adaptation plumbing, not another raw audit surface',
    'sharp_rule':'full exact >=.50, gain over zero-delta init >=.10, paired bootstrap lower>0, precision>=.95 recall>=.90',
    'classification_only_rule':'BA gain>=.05 without sharp exact rule -> retire as constructed',
    'no_gain_rule':'otherwise MICRO_LORA_NO_GAIN_AT_THIS_BOUNDARY',
    'DEV':'initialization and fixed final endpoint only; no tuning or early stopping','protected_evaluation_opened':False})
folder=OUT/'pilot-source-v01';folder.mkdir()
for n in sources:shutil.copy2(HERE/n,folder/n)
print('ONE MICRO-LORA PILOT FROZEN',flush=True)
