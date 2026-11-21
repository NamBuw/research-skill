"""Offline checks that a positive gap cannot silently rewrite search outcomes."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'research-scientist/scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('check_gap_campaign', SCRIPTS / 'check_gap_campaign.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GapCampaignTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((ROOT / 'research-scientist/references/ai-cs-gap.fixture.json').read_text())
        self.record['queries'][0].update({'source': 'openalex', 'query': 'graph shift mechanism',
                                          'family': 'direct_problem', 'campaign_query_id': 'direct-1'})
        self.record['queries'][1].update({'source': 'arxiv', 'query': 'ti:graph AND abs:shift',
                                          'family': 'closure', 'campaign_query_id': 'closure-1'})
        self.record['candidates'][0]['search_query_ids'] = ['Q1', 'Q2']
        self.campaign = {
            'format': 'research_scientist_search_campaign_v1',
            'known_seed_checks': [{'seed': {'source': 'arxiv', 'source_id': '1234.56789'},
                                   'status': 'retrieved', 'retrieved_in_query_ids': ['closure-1']}],
            'query_runs': [
                {'id': 'direct-1', 'family': 'direct_problem', 'sources': {
                    'openalex': {'status': 'complete', 'executed_query': 'graph shift mechanism', 'returned': 1}}},
                {'id': 'closure-1', 'family': 'closure', 'sources': {
                    'arxiv': {'status': 'complete', 'executed_query': 'ti:graph AND abs:shift', 'returned': 1}}}
            ]}

    def test_linked_source_rows_pass_structural_manifest_check(self):
        out = module.check(self.record, self.campaign)
        self.assertTrue(out['valid_structure_and_manifest'], out['errors'])
        self.assertEqual(out['verified_query_rows'], 2)

    def test_api_failure_cannot_be_rewritten_as_completed_kill_search(self):
        self.campaign['query_runs'][1]['sources']['arxiv']['status'] = 'http_429'
        self.campaign['query_runs'][1]['sources']['arxiv']['returned'] = 0
        out = module.check(self.record, self.campaign)
        self.assertIn('queries:Q2:status_mismatch:http_429', out['errors'])
        self.assertIn('candidates:G1:no_campaign_verified_successful_kill_search', out['errors'])

    def test_missed_positive_control_blocks_positive_gap(self):
        self.campaign['known_seed_checks'][0]['status'] = 'not_retrieved_in_campaign'
        out = module.check(self.record, self.campaign)
        self.assertIn('candidates:G1:known_positive_control_missed', out['errors'])

    def test_wrong_query_count_or_unrelated_source_cannot_supply_coverage(self):
        self.record['queries'][0]['retrieved'] = 99
        self.record['candidates'][0]['search_query_ids'] = ['Q2']
        out = module.check(self.record, self.campaign)
        self.assertIn('queries:Q1:returned_count_mismatch', out['errors'])
        self.assertIn('candidates:G1:fewer_than_two_campaign_verified_sources', out['errors'])

    def test_real_gcn_snapshot_rejects_exact_first_use_gap(self):
        fixture_dir = ROOT / 'evaluation/fixtures'
        record = json.loads((fixture_dir / 'gcn-direct-precedent-record.json').read_text())
        campaign = json.loads((fixture_dir / 'gcn-precedent-campaign.json').read_text())
        out = module.check(record, campaign)
        self.assertTrue(out['valid_structure_and_manifest'], out['errors'])
        self.assertEqual(record['candidates'][0]['disposition'], 'not_a_gap')
        record['candidates'][0]['disposition'] = 'supported_candidate'
        out = module.check(record, campaign)
        self.assertIn('candidates:G1:direct_precedent_conflicts_with_positive_gap', out['errors'])

    def test_empty_known_seed_checks_blocks_supported_candidate(self):
        self.campaign['known_seed_checks'] = []
        out = module.check(self.record, self.campaign)
        self.assertFalse(out['valid_structure_and_manifest'])
        self.assertIn('candidates:G1:known_positive_control_missing', out['errors'])

    def test_canonical_rate_limited_bot_blocked_and_source_failed_statuses(self):
        self.record['queries'][1]['status'] = 'rate_limited'
        self.record['queries'][1]['retrieved'] = 0
        self.record['queries'][1]['inspected'] = 0
        self.campaign['query_runs'][1]['sources']['arxiv']['status'] = 'rate_limited'
        self.campaign['query_runs'][1]['sources']['arxiv']['returned'] = 0
        out = module.check(self.record, self.campaign)
        self.assertNotIn('queries:Q2:status_mismatch:rate_limited', out['errors'])
        self.assertIn('candidates:G1:no_campaign_verified_successful_kill_search', out['errors'])

    def test_b1_malformed_or_non_dict_known_seed_checks_rejected(self):
        self.campaign['known_seed_checks'] = ['fake_seed']
        out = module.check(self.record, self.campaign)
        self.assertFalse(out['valid_structure_and_manifest'])
        self.assertIn('campaign:invalid_known_seed_check_entry', out['errors'])
        self.assertIn('candidates:G1:known_positive_control_missed', out['errors'])

        self.campaign['known_seed_checks'] = [{'seed': {'doi': '10.1/x'}}]
        out2 = module.check(self.record, self.campaign)
        self.assertFalse(out2['valid_structure_and_manifest'])
        self.assertIn('campaign:invalid_known_seed_check_entry', out2['errors'])

    def test_b2_stopword_only_and_negated_executed_query_rejected(self):
        self.record['queries'][0]['query'] = 'and'
        self.campaign['query_runs'][0]['query'] = 'and'
        self.campaign['query_runs'][0]['sources']['openalex']['executed_query'] = 'all:quantum AND all:optics'
        out = module.check(self.record, self.campaign)
        self.assertIn('queries:Q1:executed_query_mismatch', out['errors'])

        self.record['queries'][0]['query'] = 'domain shift calibration'
        self.campaign['query_runs'][0]['query'] = 'domain shift calibration'
        self.campaign['query_runs'][0]['sources']['openalex']['executed_query'] = (
            'all:protein NOT domain NOT shift NOT calibration'
        )
        out_neg = module.check(self.record, self.campaign)
        self.assertIn('queries:Q1:executed_query_mismatch', out_neg['errors'])

        self.campaign['query_runs'][0]['sources']['openalex']['executed_query'] = (
            'all:domain AND all:calibration -shift'
        )
        out_dash = module.check(self.record, self.campaign)
        self.assertIn('queries:Q1:executed_query_mismatch', out_dash['errors'])

        self.record['queries'][0]['query'] = 'semi-supervised graph convolutional'
        self.campaign['query_runs'][0]['query'] = 'semi-supervised graph convolutional'
        self.campaign['query_runs'][0]['sources']['openalex']['executed_query'] = (
            'all:semi-supervised AND all:graph AND all:convolutional'
        )
        out_ok = module.check(self.record, self.campaign)
        self.assertTrue(out_ok['valid_structure_and_manifest'], out_ok['errors'])

    def test_n1_field_paren_dash_paren_quoted_not_and_run_query_mismatch(self):
        self.record['queries'][0]['query'] = 'domain shift'
        self.campaign['query_runs'][0]['query'] = 'domain shift'
        for bad_exec in (
            'all:protein AND NOT ti:(domain shift)',
            'all:protein AND -(domain OR shift)',
            'all:protein NOT "domain" shift',
        ):
            self.campaign['query_runs'][0]['sources']['openalex']['executed_query'] = bad_exec
            out = module.check(self.record, self.campaign)
            self.assertIn('queries:Q1:executed_query_mismatch', out['errors'], bad_exec)

        self.campaign['query_runs'][0]['query'] = 'completely different query'
        self.campaign['query_runs'][0]['sources']['openalex']['executed_query'] = 'domain shift'
        out_run = module.check(self.record, self.campaign)
        self.assertIn('queries:Q1:executed_query_mismatch', out_run['errors'])

    def test_r3_5_nested_parens_and_colon_space_quoted_negation_rejected(self):
        self.record['queries'][0]['query'] = 'shift calibration'
        self.campaign['query_runs'][0]['query'] = 'shift calibration'
        for bad_exec in (
            'all:protein AND NOT (ti:(domain) OR ab:(shift) OR ab:(calibration))',
            'all:protein AND -(ti:(domain) OR ab:(shift))',
        ):
            self.campaign['query_runs'][0]['sources']['openalex']['executed_query'] = bad_exec
            out = module.check(self.record, self.campaign)
            self.assertIn('queries:Q1:executed_query_mismatch', out['errors'], bad_exec)

        self.record['queries'][0]['query'] = 'domain shift'
        self.campaign['query_runs'][0]['query'] = 'domain shift'
        for bad_quoted in (
            'all:protein AND NOT ti: "domain" shift',
            'all:protein -ti: "domain" shift',
        ):
            self.campaign['query_runs'][0]['sources']['openalex']['executed_query'] = bad_quoted
            out = module.check(self.record, self.campaign)
            self.assertIn('queries:Q1:executed_query_mismatch', out['errors'], bad_quoted)


if __name__ == '__main__':
    unittest.main()
