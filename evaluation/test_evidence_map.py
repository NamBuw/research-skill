"""Structural evidence-map regression checks using only fictional records."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'research-scientist'
SCRIPT = ROOT / 'scripts/check_evidence_map.py'
EXAMPLE = ROOT / 'references/evidence-map.schema-example.json'
spec = importlib.util.spec_from_file_location('check_evidence_map', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EvidenceMapTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(EXAMPLE.read_text(encoding='utf-8'))

    def test_fictional_structure_passes_with_explicit_unresolved_claim(self):
        report = module.check(self.data)
        self.assertTrue(report['ready_for_sourced_answer'])
        self.assertEqual(report['counts']['unresolved_claims'], 1)

    def test_abstract_only_cannot_support_full_source_claim(self):
        data = copy.deepcopy(self.data)
        data['sources'][0]['access'] = 'abstract'
        report = module.check(data)
        self.assertFalse(report['ready_for_sourced_answer'])
        self.assertTrue(any('original full-text' in x for x in report['issues']))

    def test_unknown_citation_and_unchecked_page_fail(self):
        data = copy.deepcopy(self.data)
        data['evidence'][0]['source_id'] = 'S404'
        data['evidence'][0]['original_checked'] = False
        report = module.check(data)
        self.assertFalse(report['ready_for_sourced_answer'])
        self.assertTrue(any('unknown source' in x for x in report['issues']))
        self.assertTrue(any('original full-text' in x for x in report['issues']))

    def test_supported_claim_cannot_be_empty(self):
        data = copy.deepcopy(self.data)
        data['claims'][0]['evidence_ids'] = []
        report = module.check(data)
        self.assertFalse(report['ready_for_sourced_answer'])
        self.assertTrue(any('asserted without evidence' in x for x in report['issues']))

    def test_empty_map_cannot_pass_as_sourced_answer(self):
        data = {'source_mode': 'supplied_corpus', 'corpus_boundary': 'No material received.',
                'sources': [], 'questions': [], 'evidence': [], 'claims': [], 'outline': []}
        report = module.check(data)
        self.assertFalse(report['ready_for_sourced_answer'])

    def test_qualified_passage_does_not_fully_support_claim(self):
        data = copy.deepcopy(self.data)
        data['evidence'][0]['relation'] = 'qualifies'
        report = module.check(data)
        self.assertFalse(report['ready_for_sourced_answer'])
        data['claims'][0]['status'] = 'qualified'
        self.assertTrue(module.check(data)['ready_for_sourced_answer'])


if __name__ == '__main__':
    unittest.main()
