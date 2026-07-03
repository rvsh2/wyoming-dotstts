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

    def test_configure_visible_device_maps_cpu_and_cuda_index(self):
        with patch.dict(os.environ, {}, clear=True):
            DotsTtsSynthesizer(device="cpu")._configure_visible_device()
            self.assertEqual(os.environ["CUDA_VISIBLE_DEVICES"], "")

        with patch.dict(os.environ, {}, clear=True):
            DotsTtsSynthesizer(device="cuda:1")._configure_visible_device()
            self.assertEqual(os.environ["CUDA_VISIBLE_DEVICES"], "1")


if __name__ == "__main__":
    unittest.main()
