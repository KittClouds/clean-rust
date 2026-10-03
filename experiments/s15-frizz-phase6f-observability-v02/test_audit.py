"""Positive controls and TRAIN-only renderer/counterfactual engineering checks."""
import unittest
from observation import *
from counterfactual import find,replace_id
from audit import root_ceiling,collision

class AuditTests(unittest.TestCase):
    def test_counterfactual_metadata_key_remap(self):
        obj={'acquisition_cost':{'old':3},'visible':['old'],'fact_table':{'old':{'id':'old'}}}
        new=replace_id(obj,'old','new')
        self.assertEqual(new['acquisition_cost'],{'new':3})
        self.assertEqual(new['fact_table'],{'new':{'id':'new'}})
        self.assertEqual(obj['acquisition_cost'],{'old':3})
    def test_observable_synonyms_not_private_id(self):
        self.assertEqual(relation_wording('supplies'),relation_wording('hands tools to'))
        self.assertNotEqual(relation_wording('supplies'),relation_wording('receives goods from'))
    def test_direct_and_unknown(self):
        k=('AT','person','room')
        self.assertEqual(primitive(k,{k},set())[0],True)
        self.assertEqual(primitive(k,set(),set())[0],None)
    def test_functional_location(self):
        self.assertEqual(primitive(('AT','person','a'),{('AT','person','b')},set())[0],False)
        self.assertEqual(primitive(('AT','other','a'),{('AT','person','b')},set())[0],None)
    def test_state_and_absence(self):
        self.assertEqual(primitive(('STATE','door','open','open'),{('STATE','door','open','closed')},set())[0],False)
        self.assertEqual(primitive(('BLOCKED','a','b'),set(),set())[0],None)
        self.assertEqual(primitive(('BLOCKED','a','b'),set(),set(),True)[0],False)
    def test_inactive_is_not_false(self):
        k=('AT','person','a');self.assertIsNone(primitive(k,set(),{k})[0])
    def test_root_collision_ceiling(self):
        result=root_ceiling({'same':['[true]','[false]'],'other':['[true]']})
        self.assertEqual(result['ambiguous_roots'],2)
        self.assertEqual(result['empirical_exact_set_ceiling'],2/3)
    def test_candidate_collision(self):
        items=[{'root':'a','renderer':'r1','legal':True,'selected':True},
               {'root':'b','renderer':'r2','legal':False,'selected':False}]
        result,_=collision({'same':items},2)
        self.assertEqual(result['ambiguous_candidate_fraction'],1)
        self.assertEqual(result['empirical_candidate_scalar_accuracy_ceiling'],.5)
    def test_real_train_renderer_clauses_and_witness(self):
        p,r=next(population('TRAIN'));replay_public(p,r)
        sim=A.sim_of(r);prep=(sim,*observable_evidence(r))
        for a in p['actions']:
            status,cs=oracle(r,a,prepared=prep)
            self.assertTrue(all(c['fact'][0] not in ('PERMISSION','SELECTED') for c in cs))
            if a['type']=='WAIT':self.assertEqual((status,cs),('CERTAIN_LEGAL',[]))
            if status!='UNRESOLVED':
                self.assertEqual(status=='CERTAIN_LEGAL',sim.legal(sim.base0,0,sim.by_id[a['id']]))
        w,_=find(p,r);self.assertIsNotNone(w)
        self.assertEqual(exact_interface(w['original_public']),exact_interface(w['alternate_public']))
        self.assertNotEqual(w['original_legal_set'],w['alternate_legal_set'])
        self.assertEqual(A.derive(w['alternate_record']).disposition,'EXECUTE')
        self.assertEqual(semantic(w['original_public'],w['original_record']),semantic(w['alternate_public'],w['alternate_record']))

if __name__=='__main__':unittest.main(verbosity=2)
