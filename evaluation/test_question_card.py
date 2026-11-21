"""Regression checks for structural RQ validation, without scientific claims."""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_question_card', ROOT / 'research-scientist/scripts/check_question_card.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class QuestionCardTests(unittest.TestCase):
    def setUp(self):
        self.card = json.loads((ROOT / 'research-scientist/references/question-card.schema-example.json').read_text())

    def test_example_passes_structure_only(self):
        result = module.check(self.card)
        self.assertTrue(result['valid_structure'])
        self.assertIn('does not verify sources', result['scope'])

    def test_identical_rival_prediction_fails(self):
        self.card['expected_if_rival'] = self.card['expected_if_focal']
        self.assertIn('focal_and_rival_expectations_identical', module.check(self.card)['errors'])

    def test_missing_causal_assumptions_fails(self):
        self.card['identification_assumptions'] = ''
        self.assertIn('causal_question_missing_identification_assumptions', module.check(self.card)['errors'])

    def test_unchecked_prior_art_warns(self):
        self.card['closest_work'] = 'Not searched'
        self.assertIn('closest_work_unchecked; do not score novelty', module.check(self.card)['warnings'])

if __name__ == '__main__':
    unittest.main()
