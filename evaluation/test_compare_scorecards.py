"""Ranking-sensitivity checks on invented papers and arbitrary ratings."""
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / 'research-scientist/scripts'
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location('compare_scorecards', SCRIPT_DIR / 'compare_scorecards.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CompareScorecardsTests(unittest.TestCase):
    def profile(self, name, importance, novelty):
        return {'id': name, 'reading_basis': 'full_text', 'closest_work': ['fictional work'],
                'ratings': {'importance': importance, 'novelty': novelty, 'soundness': 5, 'evidence': 5, 'transparency': 5, 'clarity': 5},
                'evidence_locators': {key: ['fictional section 1'] for key in module.DIMENSIONS}}

    def test_weight_change_reverses_top_paper(self):
        data = {'profiles': [self.profile('A', 9, 3), self.profile('B', 3, 9)],
                'weight_scenarios': [
                    {'importance': 45, 'novelty': 5, 'soundness': 15, 'evidence': 15, 'transparency': 10, 'clarity': 10},
                    {'importance': 5, 'novelty': 45, 'soundness': 15, 'evidence': 15, 'transparency': 10, 'clarity': 10}]}
        self.assertEqual(module.compare(data)['ranking_sensitivity'], 'top_changes_across_supplied_weights')

    def test_abstract_only_blocks_comparison(self):
        first = self.profile('A', 7, 7)
        first['reading_basis'] = 'abstract'
        data = {'profiles': [first, self.profile('B', 7, 7)],
                'weight_scenarios': [dict(zip(module.DIMENSIONS, (15, 20, 20, 20, 15, 10)))]}
        self.assertIn('full_text_not_confirmed:A', module.compare(data)['issues'])

    def test_missing_closest_work_blocks_novelty_rank(self):
        first = self.profile('A', 7, 7)
        first['closest_work'] = []
        data = {'profiles': [first, self.profile('B', 7, 7)],
                'weight_scenarios': [dict(zip(module.DIMENSIONS, (15, 20, 20, 20, 15, 10)))]}
        self.assertIn('closest_work_missing:A', module.compare(data)['issues'])

    def test_invalid_rating_is_not_hidden(self):
        first = self.profile('A', 7, 7)
        first['ratings']['clarity'] = 12
        data = {'profiles': [first, self.profile('B', 7, 7)],
                'weight_scenarios': [dict(zip(module.DIMENSIONS, (15, 20, 20, 20, 15, 10)))]}
        with self.assertRaises(ValueError):
            module.compare(data)


if __name__ == '__main__':
    unittest.main()
