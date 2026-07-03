import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import os

import numpy as np

from dotstts_wyoming.synthesizer import DotsTtsSynthesizer, SynthesisOptions


class _FakeTensor:
    def __init__(self, values):
        self.values = values

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return np.asarray(self.values, dtype=np.float32)


class _FakeRuntime:
    sample_rate = 48000

    def __init__(self):
        self.generate_calls = []
        self.stream_calls = []

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return {"audio": _FakeTensor([[0.0, 0.25, -0.25]]), "sample_rate": 48000}

    def generate_stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        yield _FakeTensor([[0.5, -0.5]])
        yield _FakeTensor([[0.25]])


class SynthesizerTests(unittest.TestCase):
    def _speaker_dir(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        profile = root / "mira"
        profile.mkdir()
        (profile / "reference.wav").write_bytes(b"wav")
        (profile / "prompt.txt").write_text("Prompt transcript.", encoding="utf-8")
        return temp

    def test_synthesize_passes_runtime_arguments(self):
        temp = self._speaker_dir()
        self.addCleanup(temp.cleanup)
        runtime = _FakeRuntime()
        synth = DotsTtsSynthesizer(
            speaker_dir=temp.name,
            default_voice="mira",
            num_steps=4,
            guidance_scale=1.2,
            seed=5,
            language="PL",
        )
        synth._runtime = runtime

        with patch.object(DotsTtsSynthesizer, "_apply_seed") as apply_seed:
            result = synth.synthesize("Ala ma kota.", options=SynthesisOptions(guidance_scale=1.5))

        self.assertEqual(result.audio.tolist(), [0.0, 0.25, -0.25])
        apply_seed.assert_called_once_with(5)
        call = runtime.generate_calls[0]
        self.assertEqual(call["text"], "Ala ma kota.")
        self.assertEqual(call["prompt_audio_path"], str(Path(temp.name) / "mira" / "reference.wav"))
        self.assertEqual(call["prompt_text"], "Prompt transcript.")
        self.assertEqual(call["num_steps"], 4)
        self.assertEqual(call["guidance_scale"], 1.5)
        self.assertEqual(call["language"], "PL")

    def test_synthesize_stream_yields_float_arrays(self):
        temp = self._speaker_dir()
        self.addCleanup(temp.cleanup)
        runtime = _FakeRuntime()
        synth = DotsTtsSynthesizer(speaker_dir=temp.name, default_voice="mira")
        synth._runtime = runtime

        chunks = [(audio.tolist(), rate) for audio, rate in synth.synthesize_stream("Streaming.", voice_name="mira")]

        self.assertEqual(chunks, [([0.5, -0.5], 48000), ([0.25], 48000)])
        self.assertEqual(runtime.stream_calls[0]["text"], "Streaming.")

    def test_gain_db_scales_output_audio(self):
        temp = self._speaker_dir()
        self.addCleanup(temp.cleanup)
        synth = DotsTtsSynthesizer(speaker_dir=temp.name, default_voice="mira", gain_db=6.0)
        synth._runtime = _FakeRuntime()

        result = synth.synthesize("Głośniej.")

        expected = 0.25 * 10 ** (6.0 / 20.0)
        self.assertAlmostEqual(float(result.audio[1]), expected, places=5)

    def test_runtime_settings_roundtrip(self):
        synth = DotsTtsSynthesizer(seed=7, gain_db=0.0)
        self.assertEqual(
            synth.runtime_settings(),
            {
                "seed": 7,
                "gain_db": 0.0,
                "num_steps": 4,
                "trim_silence": True,
                "default_voice": None,
                "language": None,
                "normalize_text": False,
            },
        )

        synth.apply_runtime_settings(
            {
                "seed": None,
                "gain_db": 12,
                "num_steps": 8,
                "trim_silence": False,
                "default_voice": "mira",
                "language": "en",
                "normalize_text": True,
            }
        )
        self.assertIsNone(synth.seed)
        self.assertEqual(synth.gain_db, 12.0)
        self.assertEqual(synth.num_steps, 8)
        self.assertFalse(synth.trim_silence)
        self.assertEqual(synth.default_voice, "mira")
        self.assertEqual(synth.language, "en")
        self.assertTrue(synth.normalize_text)

    def test_trim_silence_cuts_edges_with_padding(self):
        synth = DotsTtsSynthesizer()
        rate = 1000  # padding = 150 samples
        audio = np.zeros(3000, dtype=np.float32)
        audio[1000:1200] = 0.5
        trimmed = synth._trim_silence(audio, rate)
        self.assertEqual(len(trimmed), (1200 + 150) - (1000 - 150))
        self.assertEqual(float(np.abs(trimmed).max()), 0.5)

        synth.trim_silence = False
        self.assertEqual(len(synth._trim_silence(audio, rate)), 3000)

    def test_trim_silence_all_quiet_keeps_short_stub(self):
        # A valid (briefly silent) stream must still be produced, never zero
        # samples / zero chunks.
        synth = DotsTtsSynthesizer()
        audio = np.full(1000, 5e-5, dtype=np.float32)
        self.assertEqual(len(synth._trim_silence(audio, 1000)), 150)

        chunks = list(synth._trim_silence_stream([audio], 1000))
        self.assertEqual(sum(len(c) for c in chunks), 150)

    def test_trim_silence_stream_drops_lead_and_tail(self):
        synth = DotsTtsSynthesizer()
        rate = 1000  # padding = 150 samples
        silent = np.zeros(400, dtype=np.float32)
        speech = np.full(400, 0.5, dtype=np.float32)
        out = list(synth._trim_silence_stream([silent, silent, speech, speech, silent, silent], rate))
        total = np.concatenate(out)
        # lead: 150 padding + 800 speech + 150 tail padding
        self.assertEqual(len(total), 150 + 800 + 150)
        self.assertEqual(float(total[0]), 0.0)
        self.assertEqual(float(total[-1]), 0.0)
        self.assertEqual(float(np.abs(total).max()), 0.5)

    def test_trim_silence_stream_keeps_mid_sentence_pause(self):
        synth = DotsTtsSynthesizer()
        silent = np.zeros(400, dtype=np.float32)
        speech = np.full(400, 0.5, dtype=np.float32)
        out = list(synth._trim_silence_stream([speech, silent, silent, speech], 1000))
        self.assertEqual(len(np.concatenate(out)), 4 * 400)

    def test_configure_visible_device_maps_cpu_and_cuda_index(self):
        with patch.dict(os.environ, {}, clear=True):
            DotsTtsSynthesizer(device="cpu")._configure_visible_device()
            self.assertEqual(os.environ["CUDA_VISIBLE_DEVICES"], "")

        with patch.dict(os.environ, {}, clear=True):
            DotsTtsSynthesizer(device="cuda:1")._configure_visible_device()
            self.assertEqual(os.environ["CUDA_VISIBLE_DEVICES"], "1")


if __name__ == "__main__":
    unittest.main()
