import unittest
from context_inputs import observable_coordinates,goal_binding_matches


class CoordinatesTests(unittest.TestCase):
    def test_ambiguity_retained_and_no_substring_guess(self):
        bindings=[{'id':'e0','name':'bell','aliases':['the chime']},
                  {'id':'e1','name':'bell','aliases':[]},
                  {'id':'e2','name':'doorbell','aliases':[]}]
        self.assertEqual(goal_binding_matches({'surface':'the bell'},bindings),[0,1])
        self.assertEqual(goal_binding_matches({'surface':'the chime'},bindings),[0])
        self.assertEqual(goal_binding_matches({'surface':'unknown'},bindings),[])

    def test_global_offsets_and_role_order(self):
        row={'bindings':[{'id':'e0','name':'agent','aliases':[]},
                         {'id':'e1','name':'room','aliases':[]}],
             'actions':[{'args':{'dst':'e1','agent':'e0'}}],
             'goal_mentions':[{'role':'TARGET','surface':'the room'}],
             'WORLD_TRUTH':{'goal':'poison'}}
        roles,goals=observable_coordinates(row,100)
        self.assertEqual(roles,[[0,2,-1,-1]])
        self.assertEqual(goals,[[],[101]])


if __name__=='__main__':
    unittest.main()
