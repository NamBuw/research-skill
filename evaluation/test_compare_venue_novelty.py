"""Offline venue-panel arithmetic and evidence-gate tests."""
import importlib.util
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'research-scientist/scripts/compare_venue_novelty.py'
spec = importlib.util.spec_from_file_location('compare_venue_novelty', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
FIXTURE = ROOT / 'research-scientist/references/venue-novelty-profile.fixture.json'


class VenueNoveltyTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.as_of = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)

    def test_descriptive_panel_and_fit_arithmetic(self):
        out = module.check(self.profile, self.as_of)
        self.assertEqual(out['status'], 'structurally_checked')
        self.assertEqual(out['fit_score_out_of_10'], 8)
        self.assertEqual(out['novelty_comparison']['accepted_panel_median_score'], 6)
        self.assertEqual(len(out['novelty_comparison']['overlapping_intervals_with_ids']), 5)

    def test_unknown_budget_withholds_fit_score(self):
        self.profile['hard_constraints'][1]['status'] = 'unverified'
        self.profile['hard_constraints'][1].pop('source_url')
        out = module.check(self.profile, self.as_of)
        self.assertIsNone(out['fit_score_out_of_10'])
        self.assertIn('venue:hard_constraint_unverified;_fit_score_withheld', out['warnings'])

    def test_stale_cfp_withholds_fit_and_old_panel_withholds_comparison(self):
        self.profile['venue']['checked_at_utc'] = '2026-01-01T00:00:00Z'
        for item in self.profile['accepted_panel']:
            item['year'] = 2020
        out = module.check(self.profile, self.as_of)
        self.assertIsNone(out['fit_score_out_of_10'])
        self.assertIsNone(out['novelty_comparison'])

    def test_abstract_only_reference_or_wrong_track_blocks_comparison(self):
        self.profile['accepted_panel'][0]['reading_basis'] = 'abstract'
        self.profile['accepted_panel'][1]['track'] = 'Other track'
        out = module.check(self.profile, self.as_of)
        self.assertEqual(out['status'], 'invalid')
        self.assertIsNone(out['novelty_comparison'])

    def test_score_interval_must_include_rating(self):
        self.profile['target']['low'] = 8
        out = module.check(self.profile, self.as_of)
        self.assertIn('target:score_outside_interval', out['errors'])


if __name__ == '__main__':
    unittest.main()
