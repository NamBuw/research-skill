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

    def test_placeholder_rival_explanation_rejected(self):
        for val in ('none', 'N/A', 'unknown', 'TBD', 'not applicable',
                    'TBD - fill later', 'N/A - pending', 'none yet', 'placeholder text', 'todo: add later',
                    'To be determined later', 'Unknown yet', 'No rival explanation'):
            bad = dict(self.card)
            bad['rival_explanation'] = val
            rep = module.check(bad)
            self.assertFalse(rep['valid_structure'], val)
            self.assertIn('rival_explanation_placeholder', rep['errors'])

    def test_legitimate_rival_explanation_starting_with_unknown_allowed(self):
        ok = dict(self.card)
        ok['rival_explanation'] = 'Unknown latent confounders in annotation noise rather than model depth'
        rep = module.check(ok)
        self.assertTrue(rep['valid_structure'], rep['errors'])

    def test_r3_3_non_string_causal_identification_assumptions_no_crash(self):
        import subprocess
        import sys
        import tempfile
        for bad_val in (None, ['backdoor'], 123, {'rule': 'backdoor'}):
            bad = dict(self.card)
            bad['question_type'] = 'causal'
            bad['identification_assumptions'] = bad_val
            rep = module.check(bad)
            self.assertFalse(rep['valid_structure'], repr(bad_val))
            self.assertIn('causal_question_missing_identification_assumptions', rep['errors'])

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'card.json'
            bad = dict(self.card)
            bad['question_type'] = 'causal'
            bad['identification_assumptions'] = None
            p.write_text(json.dumps(bad), encoding='utf-8')
            proc = subprocess.run(
                [sys.executable, str(ROOT / 'research-scientist/scripts/check_question_card.py'), str(p)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn('causal_question_missing_identification_assumptions', json.loads(proc.stdout)['errors'])

if __name__ == '__main__':
    unittest.main()
