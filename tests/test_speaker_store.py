import tempfile
import unittest
from pathlib import Path

from dotstts_wyoming.speaker_store import SpeakerProfileNotFoundError, SpeakerStore


class SpeakerStoreTests(unittest.TestCase):
    def test_lists_only_profiles_with_wav_and_prompt_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid = root / "mira"
            valid.mkdir()
            (valid / "reference.wav").write_bytes(b"wav")
            (valid / "prompt.txt").write_text("Dzien dobry.", encoding="utf-8")

            missing_prompt = root / "broken"
            missing_prompt.mkdir()
            (missing_prompt / "reference.wav").write_bytes(b"wav")

            store = SpeakerStore(root)

            self.assertEqual(store.profile_names(), ["mira"])
            invalid = store.list_invalid_profiles()
            self.assertEqual(invalid[0].name, "broken")
            self.assertIn("prompt.txt", invalid[0].reason)

    def test_uses_first_sorted_wav_when_reference_name_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_dir = Path(temp_dir) / "voice"
            profile_dir.mkdir()
            (profile_dir / "b.wav").write_bytes(b"b")
            (profile_dir / "a.wav").write_bytes(b"a")
            (profile_dir / "prompt.txt").write_text("Reference text.", encoding="utf-8")

            profile = SpeakerStore(temp_dir).get_profile("voice")

            self.assertEqual(profile.prompt_audio_path.name, "a.wav")

    def test_missing_profile_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(SpeakerProfileNotFoundError):
                SpeakerStore(temp_dir).get_profile("missing")

    def test_no_requested_voice_falls_back_to_first_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_dir = Path(temp_dir) / "mira"
            profile_dir.mkdir()
            (profile_dir / "reference.wav").write_bytes(b"wav")
            (profile_dir / "prompt.txt").write_text("Dzien dobry.", encoding="utf-8")

            profile = SpeakerStore(temp_dir).get_profile(None, None)

            self.assertEqual(profile.name, "mira")

    def test_no_requested_voice_and_no_profiles_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(SpeakerProfileNotFoundError):
                SpeakerStore(temp_dir).get_profile(None, None)


if __name__ == "__main__":
    unittest.main()
