"""Smoke the bundled local manuscript tools without claiming scientific validity."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'research-scientist/modules/kdense-scientific-writing/scripts'

def command(name, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args)],
                          capture_output=True, text=True, check=False)

class BundledPaperWritingTests(unittest.TestCase):
    def test_scaffold_is_incomplete_and_linter_rejects_it(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'draft'
            created = command('scaffold_manuscript.py', '--output-dir', output,
                              '--document-id', 'local-draft', '--study-design', 'randomized_trial',
                              '--guideline', 'consort-2025')
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertFalse(json.loads(created.stdout)['summary']['submission_ready'])
            linted = command('lint_manuscript.py', output / 'manuscript.md',
                             '--manifest', output / 'manuscript_manifest.json')
            self.assertNotEqual(linted.returncode, 0)
            codes = {item['code'] for item in json.loads(linted.stdout)['issues']}
            self.assertIn('UNRESOLVED_PLACEHOLDER', codes)
            self.assertIn('CONFIDENTIALITY_REVIEW_INCOMPLETE', codes)

    def test_scaffold_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'draft'
            first = command('scaffold_manuscript.py', '--output-dir', output,
                            '--document-id', 'local-draft', '--study-design', 'randomized_trial')
            self.assertEqual(first.returncode, 0)
            second = command('scaffold_manuscript.py', '--output-dir', output,
                             '--document-id', 'local-draft', '--study-design', 'randomized_trial')
            self.assertNotEqual(second.returncode, 0)

if __name__ == '__main__':
    unittest.main()
