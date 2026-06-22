import os
import unittest
from unittest.mock import patch

from dotstts_wyoming.__main__ import parse_args
from dotstts_wyoming.synthesizer import DEFAULT_MODEL


class CliTests(unittest.TestCase):
    def test_parse_args_supports_runtime_options(self):
        args = parse_args(
            [
                "--uri",
                "tcp://0.0.0.0:10200",
                "--model",
                "rednote-hilab/dots.tts-soar",
                "--voice",
                "mira",
                "--speaker-dir",
                "/data/speakers",
                "--model-dir",
                "/data/models",
                "--device",
                "cpu",
                "--precision",
                "float16",
                "--num-steps",
                "10",
                "--guidance-scale",
                "1.4",
                "--seed",
                "7",
                "--language",
                "PL",
                "--normalize-text",
                "--optimize",
                "--samples-per-chunk",
                "2048",
                "--no-streaming",
            ]
        )

        self.assertEqual(args.uri, "tcp://0.0.0.0:10200")
        self.assertEqual(args.model, "rednote-hilab/dots.tts-soar")
        self.assertEqual(args.voice, "mira")
        self.assertEqual(args.speaker_dir, "/data/speakers")
        self.assertEqual(args.model_dir, "/data/models")
        self.assertEqual(args.device, "cpu")
        self.assertEqual(args.precision, "float16")
        self.assertEqual(args.num_steps, 10)
        self.assertEqual(args.guidance_scale, 1.4)
        self.assertEqual(args.seed, 7)
        self.assertEqual(args.language, "PL")
        self.assertTrue(args.normalize_text)
        self.assertTrue(args.optimize)
        self.assertEqual(args.samples_per_chunk, 2048)
        self.assertTrue(args.no_streaming)

    def test_parse_args_reads_env_defaults(self):
        with patch.dict(
            os.environ,
            {
                "DOTSTTS_MODEL": "custom-model",
                "DOTSTTS_NUM_STEPS": "3",
                "DOTSTTS_GUIDANCE_SCALE": "1.1",
                "DOTSTTS_SEED": "42",
                "DOTSTTS_NORMALIZE_TEXT": "true",
                "DOTSTTS_OPTIMIZE": "1",
            },
        ):
            args = parse_args([])

        self.assertEqual(args.model, "custom-model")
        self.assertEqual(args.num_steps, 3)
        self.assertEqual(args.guidance_scale, 1.1)
        self.assertEqual(args.seed, 42)
        self.assertTrue(args.normalize_text)
        self.assertTrue(args.optimize)

    def test_default_model_is_mf(self):
        self.assertEqual(DEFAULT_MODEL, "rednote-hilab/dots.tts-mf")


if __name__ == "__main__":
    unittest.main()
