"""Engineering fixtures; final release populations have separate namespaces."""
import unittest
from common import *
from generation import build_root,public
from checks import check,mutation_tests

class CoreTests(unittest.TestCase):
    def test_cue_learner_positive_control(self):
        import numpy as np
        from cheap_lr import MultinomialLogisticRegression
        x=np.asarray([[i,j] for i in range(-8,9) for j in range(-8,9)],float)
        y=np.asarray(['A' if a>b and a>0 else 'B' if b>0 else 'C' for a,b in x])
        m=MultinomialLogisticRegression().fit(x,y)
        self.assertGreater(float(np.mean(m.predict(x)==y)),.95)
        self.assertLess(m.grad_norm_,.01)
    def test_pin_ancestor(self):self.assertEqual(len(pin_ancestor()),22)
    def test_every_intent_and_pair(self):
        for i in range(len(INTENTS)):
            rows,attempt=build_root('FIXTURE',i)
            with self.subTest(intent=INTENTS[i]):
                self.assertEqual(check(rows[0]),[])
                self.assertEqual(check(rows[1]),[])
                self.assertEqual(rows[0]['SUPERVISION_ABI'],rows[1]['SUPERVISION_ABI'])
                self.assertNotEqual(public(rows[0])['input_text'],public(rows[1])['input_text'])
    def test_replay_and_mutation(self):
        rows,_=build_root('FIXTURE',0);again,_=build_root('FIXTURE',0)
        self.assertEqual(rows,again)
        self.assertTrue(all(mutation_tests(rows[0]).values()))

if __name__=='__main__':
    run=unittest.main(verbosity=2,exit=False).result
    write(OUTPUT/'engineering/ENGINEERING-TESTS.json',{'status':'PASS' if run.wasSuccessful() else 'FAIL',
      'test_groups':run.testsRun,'failures':len(run.failures),'errors':len(run.errors),
      'python':sys.version,'source_hashes':{p.name:sha(p) for p in SOURCE.glob('*.py')}})
    sys.exit(0 if run.wasSuccessful() else 1)
