"""Smallest TRAIN-selected family sets and certified gold consequence rankings."""
import itertools,math
from common import OUT,read,receipt
from targets import records
from gold import FAMILIES,collision_stats


def main():
    tr=records('TRAIN');dev=records('DEV');minimum=[]
    for size in range(1,len(FAMILIES)+1):
        for subset in itertools.combinations(FAMILIES,size):
            metric=collision_stats(tr,subset)
            if metric['oracle_tie_top1']>=.95 and metric['unique_fraction']>=.90:
                minimum.append({'families':list(subset),'TRAIN':metric,'DEV':collision_stats(dev,subset)})
        if minimum:break
    output={'smallest_sufficient_sets_TRAIN_selected':minimum,'rungs':{},'distance_rank':{}}
    for split,rows in (('TRAIN',tr),('DEV',dev)):
        result={}
        for end in range(len(FAMILIES)+1):
            use=FAMILIES[:end];top=[];mrr=[];ties=[]
            for r in rows:
                def key(j):return tuple(v for f in use for v in r['factors'][f][j])
                n=sum(key(j)==key(r['selected']) for j in r['same']);ties.append(n)
                top.append(1/n);mrr.append(sum(1/k for k in range(1,n+1))/n)
            result['type_only' if end==0 else use[-1]]={'oracle_tie_top1':sum(top)/len(top),
                'oracle_tie_MRR':sum(mrr)/len(mrr),'collision_roots':sum(x>1 for x in ties),
                'collision_candidates':sum(x-1 for x in ties),'roots':len(rows),
                'interpretation':'selected descriptor class artificially placed first; oracle ambiguity bound, not learned or deployable ranking'}
        output['rungs'][split]=result
        rankstats={}
        for label,lo,hi in (('all',0,171),('1-28',1,28),('29-64',29,64),('65-128',65,128),('129-171',129,171)):
            group=[r for r in rows if lo<=r['candidate_count']<=hi];ranks=[];unresolved=0
            for r in group:
                s=r['selected'];values=r['factors']['transition_distance'];legal=r['factors']['legality']
                # Unknown cap/state-limit(10), illegal(11), and exhausted(9) are
                # not assumed comparable to solved distances. Selected distances
                # are certified; unresolved competitors counted explicitly.
                selectable=[j for j in r['same'] if legal[j][1] and values[j][0]<9]
                unresolved+=sum(legal[j][1] and values[j][0]==10 for j in r['same'])
                ordered=sorted(selectable,key=lambda j:(values[j][0],j))
                ranks.append(ordered.index(s)+1 if s in ordered else len(r['same'])+1)
            rankstats[label]={'roots':len(group),'mean_rank':sum(ranks)/len(ranks) if ranks else None,
                'MRR':sum(1/x for x in ranks)/len(ranks) if ranks else None,
                **{f'top{k}':sum(x<=k for x in ranks)/len(ranks) if ranks else None for k in (1,3,5)},
                'unresolved_search_competitors':unresolved,'class_supported':len(group)>=200}
        output['distance_rank'][split]=rankstats
    receipt(OUT/'gold-details.json',output)


if __name__=='__main__':main()
