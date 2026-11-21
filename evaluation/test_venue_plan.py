"""Calendar and cost checks for fictional venue data only."""
import importlib.util
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_venue_plan', ROOT / 'research-scientist/scripts/check_venue_plan.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class VenuePlanTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'research-scientist/references/venue-dossier.schema-example.json').read_text())
        self.now = datetime(2026, 11, 21, 13, 0, tzinfo=timezone.utc)

    def check(self):
        return module.check(self.data, as_of=self.now)

    def test_aoe_conversion_and_unknown_fees(self):
        result = self.check()
        self.assertEqual(result['milestones_user_timezone']['abstract_registration'], '2027-01-29T18:59:00+07:00')
        self.assertEqual(result['milestones_user_timezone']['full_paper'], '2027-02-05T18:59:00+07:00')
        self.assertIsNone(result['within_budget'])

    def test_complete_mandatory_costs(self):
        for item in self.data['fees']:
            if item['mandatory']:
                item['amount'] = 100
        self.assertTrue(self.check()['within_budget'])
        self.data['fees'][0]['amount'] = 300
        self.assertFalse(self.check()['within_budget'])

    def test_omitted_category_or_currency_mismatch_blocks_affordability(self):
        for item in self.data['fees']:
            item['amount'] = 0
        self.data['fees'].pop()
        self.assertIsNone(self.check()['within_budget'])
        self.data['fees'].append({'category': 'tax', 'name': 'Tax', 'mandatory': True, 'amount': 0})
        self.data['budget_currency'] = 'EUR'
        self.assertIsNone(self.check()['within_budget'])

    def test_unverified_fee_source_blocks_positive_affordability(self):
        for item in self.data['fees']:
            item['amount'] = 0
        self.data['fees'][0].pop('source_url')
        result = self.check()
        self.assertIsNone(result['within_budget'])
        self.assertIn('Submission fee', result['unverified_fee_evidence'])

    def test_known_costs_above_budget_disprove_affordability_even_with_unknowns(self):
        self.data['fees'][0]['amount'] = 600
        self.assertFalse(self.check()['within_budget'])

    def test_verified_lower_bound_above_budget_even_if_other_fee_source_unknown(self):
        self.data['fees'][0]['amount'] = 600
        self.data['fees'][1].pop('source_url')
        result = self.check()
        self.assertFalse(result['within_budget'])
        self.assertEqual(result['verified_known_lower_bound'], 600)

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            module.parse_deadline('2027-02-04T23:59:00')

    def test_backward_schedule_uses_supplied_serial_durations(self):
        result = self.check()['backward_schedule']
        self.assertEqual(result['status'], 'start_not_yet_past_under_serial_assumption')
        self.assertEqual(result['tasks'][0]['latest_start_local'], '2027-01-17T18:59:00+07:00')
        self.assertEqual(result['tasks'][1]['latest_finish_local'], '2027-02-03T18:59:00+07:00')

    def test_invalid_fee_date_cannot_support_affordability(self):
        for fee in self.data['fees']:
            fee['amount'] = 0
        self.data['fees'][0]['checked_at'] = 'soon'
        self.assertIsNone(self.check()['within_budget'])

    def test_stale_fee_source_blocks_positive_affordability(self):
        for fee in self.data['fees']:
            fee['amount'] = 0
        self.data['fees'][0]['checked_at'] = '2026-09-01T12:00:00+00:00'
        result = self.check()
        self.assertIsNone(result['within_budget'])
        self.assertIn('Submission fee', result['stale_fee_evidence'])

if __name__ == '__main__':
    unittest.main()
