from common import *
lock();s=read(OUT/'PHASE6F-SEALED.json')
for name,h in s['artifacts'].items():
    if sha(OUT/name)!=h:raise ValueError('sealed artifact drift '+name)
if read(OUT/'fresh-process-replay.json')['status']!='PASS':raise ValueError('missing replay')
receipt(OUT/'seal-replay.json',{'status':'PASS','seal_sha256':sha(OUT/'PHASE6F-SEALED.json'),
    'artifacts_verified':len(s['artifacts']),'fresh_process':True,'protected_evaluation_opened':False})
print('SEAL REPLAY PASS',flush=True)
