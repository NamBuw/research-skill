"""Unit & end-to-end integration tests for Speech & Audio (`speech_audio`) subfield support."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "research-scientist" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import audit_alignment  # noqa: E402
import build_research_inputs  # noqa: E402
import check_engineering_diagnostics  # noqa: E402
import compare_scorecards  # noqa: E402
import compare_venue_novelty  # noqa: E402
import evaluate_submission  # noqa: E402
import gap_pipeline  # noqa: E402
import project_state  # noqa: E402
import score_math  # noqa: E402
import triage_reviews  # noqa: E402


def _run_script(script_name: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script_name), *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class TestSpeechAudioSupport(unittest.TestCase):
    def test_audit_alignment_speaker_recording_channel_and_utterance_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            # Clean speaker-disjoint splits using utterance_id + speaker_id
            clean_csv = td / "splits_clean.csv"
            clean_csv.write_text(
                "utterance_id,speaker_id,split\n"
                "utt1,spk_a,train\n"
                "utt2,spk_b,val\n"
                "utt3,spk_c,test\n",
                encoding="utf-8",
            )
            res_clean = audit_alignment.inspect_splits_csv(clean_csv, group_column="auto")
            self.assertEqual(res_clean["groups_in_multiple_splits"], 0)
            self.assertEqual(res_clean["ids_in_multiple_splits"], 0)

            # Leaked recording_id across splits
            rec_leak_csv = td / "splits_rec_leak.csv"
            rec_leak_csv.write_text(
                "utt_id,recording_id,split\n"
                "u1,rec_01,train\n"
                "u2,rec_01,test\n",
                encoding="utf-8",
            )
            res_rec = audit_alignment.inspect_splits_csv(rec_leak_csv, group_column="auto")
            self.assertEqual(res_rec["groups_in_multiple_splits"], 1)

            # Leaked channel_id with audio_id across splits
            chan_leak_csv = td / "splits_chan_leak.csv"
            chan_leak_csv.write_text(
                "audio_id,channel_id,split\n"
                "a1,mic_studio,train\n"
                "a2,mic_studio,test\n",
                encoding="utf-8",
            )
            res_chan = audit_alignment.inspect_splits_csv(chan_leak_csv, group_column="auto")
            self.assertEqual(res_chan["groups_in_multiple_splits"], 1)

    def test_engineering_diagnostics_stt_tts_and_speech_to_vector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            # 1. Low-resource STT with speaker leakage, LM decoding mismatch, and wrong WER direction
            splits_leak = td / "stt_splits.csv"
            splits_leak.write_text(
                "utterance_id,speaker_id,split\n"
                "u1,spk_1,train\n"
                "u2,spk_1,test\n",
                encoding="utf-8",
            )
            stt_bad = td / "stt_bad.json"
            stt_bad.write_text(
                json.dumps({
                    "metric_id": "wer_tonal",
                    "metric_direction": "higher",
                    "lm_decoding": {"baseline": "greedy", "candidate": "4gram_kenlm_beam"},
                    "sample_rate": {"baseline": 16000, "candidate": 24000},
                    "sanity_controls": {"majority": 0.98},
                    "baseline": {"value": 0.42, "seeds": [1, 2, 3]},
                    "candidate": {"value": 0.35, "seeds": [1, 2, 3]},
                }),
                encoding="utf-8",
            )
            diag_stt = check_engineering_diagnostics.diagnose(splits_path=splits_leak, metrics_path=stt_bad)
            self.assertEqual(diag_stt["verdict"], "ENGINEERING_BUG_DETECTED")
            cats_stt = {f["category"] for f in diag_stt["findings"]}
            self.assertIn("group_leakage_across_splits", cats_stt)
            self.assertIn("budget_or_config_mismatch", cats_stt)
            self.assertIn("metric_direction_mismatch", cats_stt)

            # 2. TTS vocoder mismatch + valid higher-is-better MOS vs lower-is-better MCD
            tts_bad = td / "tts_bad.json"
            tts_bad.write_text(
                json.dumps({
                    "metric_id": "mos",
                    "metric_direction": "lower",
                    "vocoder": {"baseline": "hifigan", "candidate": "bigvgan_v2"},
                    "sanity_controls": {"dummy": 1.1},
                    "baseline": {"value": 3.4, "seeds": [1, 2, 3]},
                    "candidate": {"value": 3.8, "seeds": [1, 2, 3]},
                }),
                encoding="utf-8",
            )
            diag_tts = check_engineering_diagnostics.diagnose(metrics_path=tts_bad)
            cats_tts = {f["category"] for f in diag_tts["findings"]}
            self.assertIn("budget_or_config_mismatch", cats_tts)
            self.assertIn("metric_direction_mismatch", cats_tts)

            # 3. Speech-to-vector matching / verification parity & clean pass
            s2v_bad = td / "s2v_bad.json"
            s2v_bad.write_text(
                json.dumps({
                    "metric_id": "eer",
                    "metric_direction": "higher",
                    "embedding_backend": {"baseline": "xvector", "candidate": "ecapa_tdnn"},
                    "score_normalization": {"baseline": "none", "candidate": "as_norm"},
                    "sanity_controls": {"random": 0.50},
                    "baseline": {"value": 0.08, "seeds": [1, 2, 3]},
                    "candidate": {"value": 0.04, "seeds": [1, 2, 3]},
                }),
                encoding="utf-8",
            )
            diag_s2v_bad = check_engineering_diagnostics.diagnose(metrics_path=s2v_bad)
            cats_s2v = {f["category"] for f in diag_s2v_bad["findings"]}
            self.assertIn("budget_or_config_mismatch", cats_s2v)
            self.assertIn("metric_direction_mismatch", cats_s2v)

            splits_clean = td / "splits_clean.csv"
            splits_clean.write_text(
                "utterance_id,speaker_id,split\n"
                "u1,spk_1,train\n"
                "u2,spk_2,val\n"
                "u3,spk_3,test\n",
                encoding="utf-8",
            )
            s2v_clean = td / "s2v_clean.json"
            s2v_clean.write_text(
                json.dumps({
                    "metric_id": "eer",
                    "metric_direction": "lower",
                    "embedding_backend": {"baseline": "ecapa_tdnn", "candidate": "ecapa_tdnn"},
                    "score_normalization": {"baseline": "as_norm", "candidate": "as_norm"},
                    "sample_rate": {"baseline": 16000, "candidate": 16000},
                    "sanity_controls": {"random": 0.50},
                    "baseline": {"value": 0.08, "seeds": [1, 2, 3]},
                    "candidate": {"value": 0.05, "seeds": [1, 2, 3]},
                }),
                encoding="utf-8",
            )
            diag_clean = check_engineering_diagnostics.diagnose(splits_path=splits_clean, metrics_path=s2v_clean)
            self.assertEqual(diag_clean["verdict"], "PASS")
            self.assertEqual(diag_clean["triage_classification"], "genuine_scientific_novelty")

    def test_speech_audio_end_to_end_across_build_gap_state_scoring_triage_and_evaluate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            # 1. Auto-builder + ProjectState with speech_audio
            built = build_research_inputs.build_inputs(
                topic="Extremely low-resource speech to text and speech-to-vector utterance matching",
                target_venue="ACM TALLIP",
                subfield_preset="speech_audio",
                offline=True,
                out_dir=td / "inputs",
            )
            self.assertEqual(built["subfield_preset"], "speech_audio")
            self.assertIn("speaker_and_session_disjoint_split", built["corpus"]["subfield_criteria"]["gap_vetting_checks"])
            for p in built["corpus"]["papers"]:
                self.assertEqual(p["reading_basis"], "metadata_only")

            st = project_state.init_state(
                project_id="speech-tallip-001",
                title="Low-resource STT + Speech-to-Vector",
                subfield_preset="speech_audio",
                target_venue="ACM TALLIP",
                target_venue_tier="q2_q3_or_tier_b",
            )
            self.assertEqual(st["subfield_preset"], "speech_audio")

            # 2. Gap pipeline speech synonym expansion + speech_audio preset hook
            corpus = {
                "S1": {
                    "id": "S1",
                    "source": "acl",
                    "family": "same_problem",
                    "year": 2024,
                    "title": "Low-resource utterance vector matching and connectionist temporal classification",
                    "abstract": "Speaker-disjoint adaptation for low-resource speech.",
                    "text": "Speaker-disjoint acoustic adaptation under unseen speakers.",
                    "access": "full_text",
                },
                "S2": {
                    "id": "S2",
                    "source": "arxiv",
                    "family": "cross_setting_analogy",
                    "year": 2023,
                    "title": "Cross-lingual time-frequency spectrogram masking for unseen speakers",
                    "abstract": "Adversarial noise robustness across channels.",
                    "text": "Channel robustness across reverberant recordings.",
                    "access": "full_text",
                },
            }
            digests = {
                "S1": {"source_id": "S1", "access": "full_text", "digest": "Unseen speaker adaptation leaves tonal OOD gap."},
                "S2": {"source_id": "S2", "access": "full_text", "digest": "Cross-channel transfer bounds established."},
            }
            cand = {
                "id": "G_SPEECH_1",
                "claim": "Zero-shot tonal speech-to-text lacks speaker-disjoint robustness verification under field noise.",
                "cited_ids": ["S1", "S2"],
                "support_ids": ["S1", "S2"],
                "engineering_checked": True,
                "sgha_critics_passed": True,
                "simplest_alternative": "Fine-tune MMS adapter with specaugment and speed perturb on matched speaker splits.",
                "ablation_over_simplest_baseline": 1.4,
                "subfield_checks": {"speaker_session_disjoint_split": True},
            }
            gp_out = gap_pipeline.run_pipeline("low resource speech", corpus, digests, [cand], subfield_preset="speech_audio")
            self.assertEqual(gp_out["exit_code"], 0)
            sv = gp_out["surviving_gaps"][0]["subfield_vetting"]
            self.assertEqual(sv["preset"], "speech_audio")
            self.assertIn("speaker_session_disjoint_split", sv["covered_checks"])

            # 3. Auto-infer failed speech controls in triage_reviews & evaluate_submission when engineering_diagnostics fails
            sc_path = td / "scorecard.json"
            sc_path.write_text(
                json.dumps({
                    "weights": {"importance": 15, "novelty": 15, "soundness": 20, "evidence": 25, "transparency": 15, "clarity": 10},
                    "ratings": {"importance": 7, "novelty": 6, "soundness": 7, "evidence": 7, "transparency": 6, "clarity": 6},
                    "venue_type": "journal_q1",
                    "subfield_preset": "speech_audio",
                    "subfield_checks": {
                        "speaker_session_disjoint_split": True,
                        "audio_metric_and_normalization_parity": True,
                        "decoding_vocoder_embedding_parity": True,
                        "speech_slice_significance_and_consent": True,
                    },
                }),
                encoding="utf-8",
            )
            eng_fail_path = td / "eng_fail.json"
            eng_fail_path.write_text(
                json.dumps({
                    "schema": "research_scientist_engineering_diagnostics_v1",
                    "verdict": "ENGINEERING_BUG_DETECTED",
                    "findings": [
                        {"category": "group_leakage_across_splits", "severity": "error", "location": "splits.csv", "detail": "2 speaker_id groups leak across splits."},
                        {"category": "budget_or_config_mismatch", "severity": "error", "location": "embedding_backend", "detail": "Mismatched embedding_backend between baseline and candidate."},
                    ],
                }),
                encoding="utf-8",
            )
            mock_res = triage_reviews.run_mock_review(
                {
                    "scorecard": json.loads(sc_path.read_text(encoding="utf-8")),
                    "engineering_diagnostics": json.loads(eng_fail_path.read_text(encoding="utf-8")),
                },
                subfield_preset="speech_audio",
            )
            spa = mock_res["subfield_preset_audit"]
            self.assertEqual(spa["active_preset"], "speech_audio")
            self.assertEqual(spa["status"], "FAIL")
            self.assertIn("speaker_session_disjoint_split", spa["failed_checks"])
            self.assertIn("decoding_vocoder_embedding_parity", spa["failed_checks"])

            eval_out_path = td / "eval_out.json"
            proc = _run_script(
                "evaluate_submission.py",
                [
                    "--scorecard", str(sc_path),
                    "--engineering-diagnostics", str(eng_fail_path),
                    "--subfield-preset", "speech_audio",
                    "--out", str(eval_out_path),
                    "--compact",
                ],
            )
            self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
            eval_full = json.loads(eval_out_path.read_text(encoding="utf-8"))
            self.assertEqual(eval_full["subfield_preset"], "speech_audio")
            self.assertFalse(eval_full["ready_to_submit"])
            self.assertIn("speaker_session_disjoint_split", eval_full["subfield_criteria"]["missing_checks"])
            self.assertIn("decoding_vocoder_embedding_parity", eval_full["subfield_criteria"]["missing_checks"])

            # 4. Passing compare_scorecards + compare_venue_novelty CLI checks with speech_audio
            sm_proc = _run_script("score_math.py", [str(sc_path), "--subfield-preset", "speech_audio"])
            self.assertEqual(sm_proc.returncode, 0, sm_proc.stderr)
            sm_data = json.loads(sm_proc.stdout)
            self.assertEqual(sm_data["subfield_readiness"]["preset"], "speech_audio")
            self.assertTrue(sm_data["subfield_readiness"]["all_required_verified"])
            self.assertIsNotNone(compare_scorecards.SUBFIELD_PRESETS.get("speech_audio"))
            self.assertIsNotNone(compare_venue_novelty.SUBFIELD_PRESETS.get("speech_audio"))


if __name__ == "__main__":
    unittest.main()
