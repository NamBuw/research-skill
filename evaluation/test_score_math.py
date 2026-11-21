"""Regression checks for score arithmetic and missing-data integrity."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'research-scientist/scripts/score_math.py'
spec = importlib.util.spec_from_file_location('score_math', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ScoreMathTests(unittest.TestCase):
    def setUp(self):
        self.weights = dict(zip(module.DIMENSIONS, (15, 20, 20, 20, 15, 10)))
        self.ratings = dict.fromkeys(module.DIMENSIONS, 7)

    def test_valid_weighted_score(self):
        self.assertEqual(module.score({'weights': self.weights, 'ratings': self.ratings})['overall'], 7)

    def test_missing_dimension_prevents_overall(self):
        self.ratings['novelty'] = None
        self.assertEqual(module.score({'weights': self.weights, 'ratings': self.ratings})['status'], 'not_comparable')

    def test_invalid_value_is_not_hidden_by_missing_dimension(self):
        self.ratings['novelty'] = None
        self.ratings['clarity'] = 12
        with self.assertRaises(ValueError):
            module.score({'weights': self.weights, 'ratings': self.ratings})

    def test_invalid_weight_total_rejected(self):
        self.weights['clarity'] = 9
        with self.assertRaises(ValueError):
            module.score({'weights': self.weights, 'ratings': self.ratings})

if __name__ == '__main__':
    unittest.main()
