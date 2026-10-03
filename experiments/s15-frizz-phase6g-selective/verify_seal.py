from common import *
lock();s=read(OUT/'PHASE6G-SEALED.json')
for p,h in s['artifacts'].items():
    if sha(OUT/p)!=h:raise ValueError('sealed artifact drift '+p)
receipt(OUT/'seal-replay.json',{'status':'PASS','artifacts':len(s['artifacts']),'seal_sha256':sha(OUT/'PHASE6G-SEALED.json'),
    'fresh_process':True,'protected_evaluation_opened':False})
print('SEAL REPLAY PASS',flush=True)
