"""Structural chain checks for empirical AI/CS gap-to-experiment plans."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'research-scientist/scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('check_ai_cs_research_plan', SCRIPTS / 'check_ai_cs_research_plan.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
REFS = ROOT / 'research-scientist/references'


def fixture(name):
    return json.loads((REFS / name).read_text(encoding='utf-8'))


class AIPlanTests(unittest.TestCase):
    def setUp(self):
        self.gap = fixture('ai-cs-gap.fixture.json')
        self.rq = fixture('ai-cs-question.fixture.json')
        self.plan = fixture('ai-cs-experiment-plan.fixture.json')

    def test_fixture_is_reviewable_without_claiming_valid_science(self):
        result = module.check(self.gap, self.rq, self.plan)
        self.assertEqual(result['status'], 'structurally_reviewable')
        self.assertIn('reference_reproduction', result['engineering_checks_pending_or_failed'])
        self.assertEqual(result['gap_interpretation_gate'], 'requires_source_and_experiment_review')

    def test_failed_implementation_cannot_promote_pending_engineering_to_confirmation(self):
        self.gap['candidates'][0]['trigger'] = 'failed_implementation'
        self.gap['candidates'][0]['engineering_status'] = 'implementation_checked'
        self.plan['claim_mode'] = 'confirmatory'
        result = module.check(self.gap, self.rq, self.plan)
        self.assertIn('plan:confirmatory_failure_claim_requires_passed_engineering_checks', result['errors'])
        self.assertEqual(result['gap_interpretation_gate'], 'engineering_unresolved')

    def test_test_set_tuning_and_nondiscriminating_prediction_rejected(self):
        self.plan['experiments'][0]['tuning_data_role'] = 'test'
        self.plan['experiments'][0]['predicted_if_rival'] = self.plan['experiments'][0]['predicted_if_focal']
        result = module.check(self.gap, self.rq, self.plan)
        self.assertIn('experiments:0:invalid_tuning_data_role_or_test_set_used_for_tuning', result['errors'])
        self.assertIn('experiments:0:predictions_do_not_discriminate', result['errors'])

    def test_unread_close_work_and_seen_outcomes_block_confirmatory_claim(self):
        self.plan['claim_mode'] = 'confirmatory'
        self.plan['unresolved_close_work_ids'] = ['W-UNREAD']
        self.rq['prior_outcome_exposure'] = 'Outcomes seen'
        result = module.check(self.gap, self.rq, self.plan)
        self.assertIn('plan:unread_close_work_blocks_confirmatory_novelty', result['errors'])
        self.assertIn('plan:seen_outcomes_cannot_be_called_prespecified_confirmation', result['errors'])

    def test_mechanism_claim_needs_discriminating_followup(self):
        self.plan['experiments'] = [self.plan['experiments'][0]]
        result = module.check(self.gap, self.rq, self.plan)
        self.assertIn('experiments:mechanism_claim_needs_ablation_or_negative_control', result['errors'])

    def test_identical_conditions_are_not_a_comparison(self):
        self.plan['experiments'][0]['comparator_condition'] = self.plan['experiments'][0]['focal_condition']
        result = module.check(self.gap, self.rq, self.plan)
        self.assertIn('experiments:0:focal_and_comparator_conditions_identical', result['errors'])

    def test_confirmatory_enforces_all_engineering_checks_and_campaign(self):
        self.gap['candidates'][0]['trigger'] = 'benchmark_observation'
        self.plan['claim_mode'] = 'confirmatory'
        for k in self.plan['engineering_checks']:
            self.plan['engineering_checks'][k]['status'] = 'passed'
        self.plan['engineering_checks']['baseline_fidelity']['status'] = 'failed'
        result = module.check(self.gap, self.rq, self.plan)
        self.assertEqual(result['status'], 'invalid')
        self.assertIn('plan:confirmatory_claim_requires_campaign_manifest', result['errors'])
        self.assertIn('engineering_checks:baseline_fidelity:confirmatory_requires_passed_check', result['errors'])

    def test_b11_confirmatory_rejects_not_applicable_engineering_check(self):
        self.gap['candidates'][0]['trigger'] = 'novel_idea'
        self.plan['claim_mode'] = 'confirmatory'
        for k in self.plan['engineering_checks']:
            self.plan['engineering_checks'][k]['status'] = 'passed'
        self.plan['engineering_checks']['split_integrity']['status'] = 'not_applicable'
        result = module.check(self.gap, self.rq, self.plan)
        self.assertEqual(result['status'], 'invalid')
        self.assertIn('engineering_checks:split_integrity:confirmatory_requires_passed_check', result['errors'])

    def test_cli_exits_nonzero_on_invalid_plan(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            self.plan['claim_mode'] = 'confirmatory'
            gp, rqp, pp = t / 'g.json', t / 'r.json', t / 'p.json'
            gp.write_text(json.dumps(self.gap), encoding='utf-8')
            rqp.write_text(json.dumps(self.rq), encoding='utf-8')
            pp.write_text(json.dumps(self.plan), encoding='utf-8')
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_ai_cs_research_plan.py'), str(gp), str(rqp), str(pp)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 1)


if __name__ == '__main__':
    unittest.main()
