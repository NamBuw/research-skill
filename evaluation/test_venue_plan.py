"""Calendar and cost checks for fictional venue data only."""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_venue_plan', ROOT / 'research-scientist/scripts/check_venue_plan.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class VenuePlanTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'research-scientist/references/venue-dossier.schema-example.json').read_text())

    def test_aoe_conversion_and_unknown_fees(self):
        result = module.check(self.data)
        self.assertEqual(result['milestones_user_timezone']['abstract_registration'], '2027-01-29T18:59:00+07:00')
        self.assertEqual(result['milestones_user_timezone']['full_paper'], '2027-02-05T18:59:00+07:00')
        self.assertIsNone(result['within_budget'])

    def test_complete_mandatory_costs(self):
        for item in self.data['fees']:
            if item['mandatory']:
                item['amount'] = 100
        self.assertTrue(module.check(self.data)['within_budget'])
        self.data['fees'][0]['amount'] = 300
        self.assertFalse(module.check(self.data)['within_budget'])

    def test_omitted_category_or_currency_mismatch_blocks_affordability(self):
        for item in self.data['fees']:
            item['amount'] = 0
        self.data['fees'].pop()
        self.assertIsNone(module.check(self.data)['within_budget'])
        self.data['fees'].append({'category': 'tax', 'name': 'Tax', 'mandatory': True, 'amount': 0})
        self.data['budget_currency'] = 'EUR'
        self.assertIsNone(module.check(self.data)['within_budget'])

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            module.parse_deadline('2027-02-04T23:59:00')

if __name__ == '__main__':
    unittest.main()
