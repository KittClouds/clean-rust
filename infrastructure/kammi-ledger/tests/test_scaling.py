import unittest
from ledgerd.identity import canonical
from ledgerd.seals import make_seal, verify_lineage


class ScalingTests(unittest.TestCase):
    def test_deep_shared_dag_visits_each_object_once(self):
        member = "sha256:" + "1" * 64
        seals, loads, verifies = {}, [], []
        parent = None
        for _ in range(2048):
            payload, root = make_seal([member], [parent] if parent else [])
            seals[root] = canonical(payload)
            parent = root
        def load(root):
            loads.append(root)
            return seals[root]
        def verify(identity):
            verifies.append(identity)
            return True
        self.assertEqual(verify_lineage(parent, load, verify), [member])
        self.assertEqual(len(loads), 2048)
        self.assertEqual(len(verifies), 1)
