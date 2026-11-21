"""Structural manuscript ledger checks with fictional fixtures."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_manuscript_ledger', ROOT / 'research-scientist/scripts/check_manuscript_ledger.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ManuscriptLedgerTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'research-scientist/references/manuscript-ledger.schema-example.json').read_text())

    def test_complete_fictional_structure(self):
        self.assertEqual(module.check(self.data)['status'], 'structure_passed')

    def test_claim_without_verified_locator_fails(self):
        self.data['sources'][0]['verified'] = False
        self.assertIn('material_claim_without_verified_locator:C1', module.check(self.data)['issues'])

    def test_recombination_novelty_requires_difference_evidence(self):
        method = self.data['methods'][0]
        method['novelty_claimed'] = True
        method['grand_name'] = True
        issues = module.check(self.data)['issues']
        self.assertIn('unsupported_method_novelty:M1', issues)
        self.assertIn('inflated_method_name:M1', issues)

    def test_grand_name_still_flagged_with_declared_difference(self):
        method = self.data['methods'][0]
        method['grand_name'] = True
        method['difference_evidence'] = 'Fictional result table 2'
        self.assertIn('inflated_method_name:M1', module.check(self.data)['issues'])

    def test_reused_method_cannot_be_claimed_as_new_method(self):
        method = self.data['methods'][0]
        method['origin'] = 'reused'
        method['novelty_claimed'] = True
        method['difference_evidence'] = 'Fictional result table 2'
        method['closest_work_source_ids'] = ['E2']
        method['human_adjudication'] = {'reviewer': 'fictional_author', 'date': '2026-11-21', 'rationale': 'fictional'}
        self.assertIn('reused_method_claimed_as_new:M1', module.check(self.data)['issues'])

    def test_numeric_mismatch_fails(self):
        self.data['numeric_facts'][0]['occurrences'][1]['value'] = 0.72
        self.assertIn('numeric_fact_mismatch:N1', module.check(self.data)['issues'])

    def test_unknown_source_and_duplicate_claim(self):
        other = copy.deepcopy(self.data['claims'][0])
        other['source_ids'] = ['E9']
        self.data['claims'].append(other)
        issues = module.check(self.data)['issues']
        self.assertIn('duplicate_claim:C1', issues)
        self.assertIn('unknown_source:C1:E9', issues)


if __name__ == '__main__':
    unittest.main()
