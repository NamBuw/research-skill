"""Smoke the bundled ResearchRadar quote verifier offline."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[1] /
          'research-scientist/modules/researchradar/problem-statement-finder/scripts/radar.py')

class BundledResearchRadarTests(unittest.TestCase):
    def test_quote_verification_requires_exact_words_and_case(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'reviews.json'
            source.write_text(json.dumps({'review': 'The comparison omitted a matched baseline.'}), encoding='utf-8')
            yes = subprocess.run([sys.executable, str(SCRIPT), 'verify', str(source),
                                  'comparison omitted a matched baseline'], capture_output=True, text=True)
            no = subprocess.run([sys.executable, str(SCRIPT), 'verify', str(source),
                                 'Comparison omitted a matched baseline'], capture_output=True, text=True)
            self.assertEqual(yes.returncode, 0)
            self.assertTrue(json.loads(yes.stdout)['all_found'])
            self.assertEqual(no.returncode, 1)
            self.assertFalse(json.loads(no.stdout)['all_found'])

if __name__ == '__main__':
    unittest.main()
