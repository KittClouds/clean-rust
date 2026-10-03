import unittest
from adapter import align,model_inputs

class Tests(unittest.TestCase):
    def fixture(self):
        p={'world_id':'w','actions':[{'id':'a','type':'MOVE'}],**{k:[] for k in ('input_text','goal_mentions','bindings','requests')}}
        a={'candidate_order':['a'],'candidates':[{'id':'a'}],'selected_action_eligible':True,
           'selected_action_index':0,'selected_action_id':'a','optimal_action_ids':['a']}
        return p,{'world_id':'w','SUPERVISION_ABI':a}
    def test_good(self):p,t=self.fixture();self.assertIs(align(p,t),t['SUPERVISION_ABI'])
    def test_join(self):
        p,t=self.fixture();t['world_id']='other'
        with self.assertRaises(ValueError):align(p,t)
    def test_selected(self):
        p,t=self.fixture();t['SUPERVISION_ABI']['selected_action_id']='b'
        with self.assertRaises(ValueError):align(p,t)
    def test_padding_not_identity(self):
        p,t=self.fixture();t['SUPERVISION_ABI']['candidate_order']=['PAD']
        with self.assertRaises(ValueError):align(p,t)
    def test_firewall(self):p,t=self.fixture();p['TARGETS']=123;self.assertNotIn('TARGETS',model_inputs(p))

if __name__=='__main__':unittest.main()
