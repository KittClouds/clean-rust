import unittest
from audit_release import normalized, split_files, identity


class ReleaseBoundaryTests(unittest.TestCase):
    def test_windows_paths(self):
        self.assertEqual(normalized('public\\TRAIN\\part.gz'), 'public/TRAIN/part.gz')

    def test_only_train_dev(self):
        files = {'public\\TRAIN\\a': 'a', 'protected/evaluation-truth/a': 'b',
                 'public/EVAL/a': 'c', 'public/DEV/a': 'd'}
        self.assertEqual(split_files(files, 'TRAIN', 'public'), {'public/TRAIN/a': 'a'})
        with self.assertRaises(ValueError):
            split_files(files, 'EVAL', 'public')

    def test_traversal_rejected(self):
        for name in ('../public/TRAIN/a', '/public/TRAIN/a', 'C:/public/TRAIN/a'):
            with self.assertRaises(ValueError):
                normalized(name)

    def test_binding_order_independent(self):
        self.assertEqual(identity({'a': '1', 'b': '2'}), identity({'b': '2', 'a': '1'}))
        self.assertNotEqual(identity({}), identity({'a': '1'}))


if __name__ == '__main__':
    unittest.main()
