"""Regression checks for gap-record structure, not scientific gap truth."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_gap_record', ROOT / 'research-scientist/scripts/check_gap_record.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GapRecordTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((ROOT / 'research-scientist/references/gap-record.schema-example.json').read_text())

    def test_fixture_passes_with_warning_about_empty_counterevidence(self):
        report = module.check(self.record)
        self.assertTrue(report['valid_structure'])
        self.assertTrue(report['warnings'])

    def test_abstract_only_support_blocks_positive_gap(self):
        self.record['evidence'][0]['access'] = 'abstract'
        report = module.check(self.record)
        self.assertIn('candidates:G1:support_not_checked_in_full_text', report['errors'])

    def test_unread_closest_work_blocks_positive_gap(self):
        self.record['closest_works'][0]['access'] = 'abstract'
        report = module.check(self.record)
        self.assertIn('candidates:G1:closest_work_unread', report['errors'])

    def test_closest_work_flag_does_not_override_abstract_locator(self):
        self.record['evidence'][0]['access'] = 'abstract'
        report = module.check(self.record)
        self.assertIn('candidates:G1:closest_work_unread', report['errors'])

    def test_direct_precedent_conflicts_with_positive_gap(self):
        self.record['closest_works'][0]['relation'] = 'direct_precedent'
        report = module.check(self.record)
        self.assertIn('candidates:G1:direct_precedent_conflicts_with_positive_gap', report['errors'])

    def test_failed_kill_search_is_not_completed(self):
        self.record['queries'][1]['status'] = 'rate_limited'
        report = module.check(self.record)
        self.assertIn('candidates:G1:no_completed_kill_search', report['errors'])

    def test_future_work_quote_alone_does_not_promote_gap(self):
        self.record['evidence'][0]['role'] = 'author_future_work'
        report = module.check(self.record)
        self.assertIn('candidates:G1:author_future_work_alone_cannot_establish_gap', report['errors'])

    def test_unrelated_query_cannot_count_as_kill_search(self):
        self.record['queries'][1]['family'] = 'direct_problem'
        report = module.check(self.record)
        self.assertIn('candidates:G1:no_completed_kill_search', report['errors'])

    def test_uninspected_kill_search_hits_block_positive_gap(self):
        self.record['queries'][1]['inspected'] = 0
        report = module.check(self.record)
        self.assertIn('candidates:G1:kill_search_retrieved_records_unscreened', report['errors'])

    def test_closest_work_needs_source_locator(self):
        self.record['closest_works'][0]['evidence_ids'] = []
        report = module.check(self.record)
        self.assertIn('candidates:G1:closest_work_has_no_locator_evidence', report['errors'])

    def test_closest_work_evidence_must_identify_same_source(self):
        self.record['closest_works'][0]['source_id'] = 'DifferentStudy'
        report = module.check(self.record)
        self.assertIn('closest_works:W1:evidence_source_mismatch:E1', report['errors'])

    def test_single_index_needs_explicit_exception(self):
        self.record['queries'][1]['source'] = self.record['queries'][0]['source']
        report = module.check(self.record)
        self.assertIn('candidates:G1:single_source_or_query_family_without_exception', report['errors'])
        self.record['candidates'][0]['coverage_exception'] = 'Only one historical archive covers this bounded collection'
        second = module.check(self.record)
        self.assertTrue(second['valid_structure'])
        self.assertIn('candidates:G1:coverage_exception_requires_scientific_review', second['warnings'])

    def test_invalid_query_count_reports_error_instead_of_crashing(self):
        self.record['queries'][1]['retrieved'] = 'many'
        report = module.check(self.record)
        self.assertIn('queries:Q2:invalid_retrieved_count', report['errors'])

    def test_local_failure_needs_engineering_diagnosis(self):
        candidate = self.record['candidates'][0]
        candidate['trigger'] = 'failed_implementation'
        candidate['engineering_status'] = 'not_checked'
        report = module.check(self.record)
        self.assertIn('candidates:G1:engineering_failure_unresolved', report['errors'])

    def test_broken_evidence_link_is_rejected(self):
        self.record['candidates'][0]['support_evidence_ids'] = ['missing']
        report = module.check(self.record)
        self.assertIn('candidates:G1:support_evidence_ids:unknown_id:missing', report['errors'])

    def test_early_signal_does_not_require_positive_gap_gate(self):
        self.record['candidates'][0]['disposition'] = 'early_signal'
        self.record['evidence'][0]['access'] = 'abstract'
        self.record['queries'][1]['status'] = 'failed'
        self.assertTrue(module.check(self.record)['valid_structure'])

    def test_any_unread_closest_work_blocks_positive_gap(self):
        self.record['evidence'].append({
            'id': 'E2', 'source_id': 'FictionalStudy-B', 'study_id': 'S2',
            'locator': 'Abstract only', 'claim': 'Abstract claim',
            'role': 'result', 'access': 'abstract',
        })
        self.record['closest_works'].append({
            'id': 'W2', 'source_id': 'FictionalStudy-B', 'relation': 'partial_precedent',
            'access': 'abstract', 'difference': 'Unread', 'evidence_ids': ['E2'],
        })
        self.record['candidates'][0]['closest_work_ids'] = ['W1', 'W2']
        report = module.check(self.record)
        self.assertIn('candidates:G1:closest_work_unread', report['errors'])

    def test_bot_blocked_and_source_failed_are_valid_query_states(self):
        self.record['queries'][0]['status'] = 'bot_blocked'
        self.record['queries'][0]['retrieved'] = 0
        self.record['queries'][0]['inspected'] = 0
        report = module.check(self.record)
        self.assertNotIn('queries:Q1:invalid_status', report['errors'])

    def test_evidence_dir_verifies_quotes_and_page_bounds(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ev_dir = Path(tmp)
            (ev_dir / 'FictionalStudy-A.json').write_text(json.dumps({
                'format': 'research_scientist_pdf_blocks_v1',
                'pages': [
                    [{'type': 'paragraph', 'page_idx': 0, 'text': 'Intro page 1'}],
                    [{'type': 'paragraph', 'page_idx': 1, 'text': 'Section 3, fictional fixture: The comparison cannot distinguish two explanations in this setting.'}],
                ],
            }), encoding='utf-8')
            ok = module.check(self.record, evidence_dir=ev_dir)
            self.assertTrue(ok['valid_structure'], ok['errors'])

            bad = copy.deepcopy(self.record)
            bad['evidence'][0]['claim'] = 'Fabricated quote missing from disk'
            bad_rep = module.check(bad, evidence_dir=ev_dir)
            self.assertIn('evidence:E1:locator_quote_not_found', bad_rep['errors'])

            bad_pg = copy.deepcopy(self.record)
            bad_pg['evidence'][0]['locator'] = 'Page 99 Section 3'
            pg_rep = module.check(bad_pg, evidence_dir=ev_dir)
            self.assertIn('evidence:E1:locator_page_out_of_range', pg_rep['errors'])

    def test_b3_stopword_quote_and_negation_inverted_quote_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ev_dir = Path(tmp)
            (ev_dir / 'FictionalStudy-A.json').write_text(json.dumps({
                'format': 'research_scientist_pdf_blocks_v1',
                'pages': [[{'type': 'paragraph', 'page_idx': 0, 'text': 'Temperature scaling degrades sharply under domain shift.'}]],
            }), encoding='utf-8')
            short_stop = copy.deepcopy(self.record)
            short_stop['evidence'][0]['quote'] = 'We do not'
            rep_short = module.check(short_stop, evidence_dir=ev_dir)
            self.assertIn('evidence:E1:locator_quote_not_found', rep_short['errors'])

            neg_inv = copy.deepcopy(self.record)
            neg_inv['evidence'][0]['quote'] = 'No temperature scaling degrades sharply under domain shift.'
            rep_neg = module.check(neg_inv, evidence_dir=ev_dir)
            self.assertIn('evidence:E1:locator_quote_not_found', rep_neg['errors'])

    def test_b4_blank_page_does_not_fallback_to_all_text(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ev_dir = Path(tmp)
            (ev_dir / 'FictionalStudy-A.json').write_text(json.dumps({
                'format': 'research_scientist_pdf_blocks_v1',
                'pages': [
                    [{'type': 'paragraph', 'page_idx': 0, 'text': 'Section 1: The comparison cannot distinguish two explanations in this setting.'}],
                    [],
                ],
            }), encoding='utf-8')
            bad = copy.deepcopy(self.record)
            bad['evidence'][0]['locator'] = 'page 2, Section 1'
            rep = module.check(bad, evidence_dir=ev_dir)
            self.assertIn('evidence:E1:locator_quote_not_found', rep['errors'])

    def test_b5_supported_candidate_zero_matched_evidence_files_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ev_dir = Path(tmp)
            (ev_dir / 'UnrelatedPaper.json').write_text(json.dumps({
                'format': 'research_scientist_pdf_blocks_v1',
                'pages': [[{'type': 'paragraph', 'page_idx': 0, 'text': 'Completely unrelated document.'}]],
            }), encoding='utf-8')
            rep = module.check(self.record, evidence_dir=ev_dir)
            self.assertFalse(rep['valid_structure'])
            self.assertIn('candidates:G1:evidence_dir:no_candidate_evidence_matched', rep['errors'])

    def test_minor1_null_evidence_ids_returns_errors_without_typeerror(self):
        bad = copy.deepcopy(self.record)
        bad['closest_works'][0]['evidence_ids'] = None
        rep = module.check(bad)
        self.assertFalse(rep['valid_structure'])
        self.assertIn('closest_works:W1:evidence_ids:must_be_id_list', rep['errors'])

    def test_n2_reverse_negation_cross_sentence_bleed_and_contractions_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ev_dir = Path(tmp)
            (ev_dir / 'FictionalStudy-A.json').write_text(json.dumps({
                'format': 'research_scientist_pdf_blocks_v1',
                'pages': [[{'type': 'paragraph', 'page_idx': 0,
                            'text': 'We never observe that temperature scaling degrades sharply under domain shift. Prior models introduce no extra latency.'}]],
            }), encoding='utf-8')
            rev = copy.deepcopy(self.record)
            rev['evidence'][0]['locator'] = 'page 1'
            rev['evidence'][0]['quote'] = 'Temperature scaling degrades sharply under domain shift.'
            self.assertIn('evidence:E1:locator_quote_not_found', module.check(rev, evidence_dir=ev_dir)['errors'])

            (ev_dir / 'FictionalStudy-A.json').write_text(json.dumps({
                'format': 'research_scientist_pdf_blocks_v1',
                'pages': [[{'type': 'paragraph', 'page_idx': 0,
                            'text': 'Temperature scaling degrades sharply under domain shift. Prior models introduce no extra latency.'}]],
            }), encoding='utf-8')
            bleed = copy.deepcopy(self.record)
            bleed['evidence'][0]['locator'] = 'page 1'
            bleed['evidence'][0]['quote'] = 'No temperature scaling degrades sharply under domain shift.'
            self.assertIn('evidence:E1:locator_quote_not_found', module.check(bleed, evidence_dir=ev_dir)['errors'])

            (ev_dir / 'FictionalStudy-A.json').write_text(json.dumps({
                'format': 'research_scientist_pdf_blocks_v1',
                'pages': [[{'type': 'paragraph', 'page_idx': 0,
                            'text': "Temperature scaling under severe domain shift can't degrade accuracy noticeably."}]],
            }), encoding='utf-8')
            contr = copy.deepcopy(self.record)
            contr['evidence'][0]['locator'] = 'page 1'
            contr['evidence'][0]['quote'] = 'Temperature scaling under severe domain shift degrades accuracy noticeably.'
            self.assertIn('evidence:E1:locator_quote_not_found', module.check(contr, evidence_dir=ev_dir)['errors'])

    def test_r3_4_abbreviation_periods_and_unable_to_reverse_negation_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ev_dir = Path(tmp)
            for pdf_text in (
                'We never observe, e.g., temperature scaling degrades sharply under domain shift.',
                'We do not observe (see Sec. 2) that temperature scaling degrades sharply under domain shift.',
                "We never observe that Dr. Smith's method causes temperature scaling degrades sharply under domain shift.",
                'Prior baselines are unable to show that temperature scaling degrades sharply under domain shift.',
            ):
                (ev_dir / 'FictionalStudy-A.json').write_text(json.dumps({
                    'format': 'research_scientist_pdf_blocks_v1',
                    'pages': [[{'type': 'paragraph', 'page_idx': 0, 'text': pdf_text}]],
                }), encoding='utf-8')
                rev = copy.deepcopy(self.record)
                rev['evidence'][0]['locator'] = 'page 1'
                rev['evidence'][0]['quote'] = 'Temperature scaling degrades sharply under domain shift.'
                self.assertIn('evidence:E1:locator_quote_not_found', module.check(rev, evidence_dir=ev_dir)['errors'], pdf_text)

            # Matching "unable to" quote is allowed
            ok = copy.deepcopy(self.record)
            ok['evidence'][0]['locator'] = 'page 1'
            ok['evidence'][0]['quote'] = 'Prior baselines are unable to show that temperature scaling degrades sharply under domain shift.'
            self.assertTrue(module.check(ok, evidence_dir=ev_dir)['valid_structure'])


if __name__ == '__main__':
    unittest.main()
