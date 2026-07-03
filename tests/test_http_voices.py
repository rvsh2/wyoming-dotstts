import io
import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from dotstts_wyoming import server as http_server
from dotstts_wyoming.synthesizer import DotsTtsSynthesizer


def _tone_wav_bytes(seconds=0.3, rate=16000):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        frames = int(seconds * rate)
        wav_file.writeframes(b"".join(struct.pack("<h", 8000 if i % 50 < 25 else -8000) for i in range(frames)))
    return buffer.getvalue()


class VoiceEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self._old_service = http_server.service
        http_server.service = DotsTtsSynthesizer(speaker_dir=self.temp.name)
        self.addCleanup(self._restore)
        self.client = TestClient(http_server.app)
        self.env = patch.dict(os.environ, {"DOTSTTS_API_TOKEN": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def _restore(self):
        http_server.service = self._old_service

    def _upload(self, name="nowy", prompt="Testowa transkrypcja.", **extra):
        return self.client.post(
            "/voices",
            data={"name": name, "prompt": prompt, **extra},
            files={"audio": ("sample.wav", _tone_wav_bytes(), "audio/wav")},
        )

    def test_upload_creates_profile_with_converted_reference(self):
        response = self._upload()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("nowy", response.json()["voices"])

        profile_dir = Path(self.temp.name) / "nowy"
        self.assertTrue((profile_dir / "prompt.txt").exists())
        with wave.open(str(profile_dir / "reference.wav")) as wav_file:
            self.assertEqual(wav_file.getframerate(), 24000)
            self.assertEqual(wav_file.getnchannels(), 1)

        listing = self.client.get("/voices").json()
        self.assertEqual(listing["voices"], ["nowy"])
        self.assertEqual(listing["valid"][0]["prompt_text"], "Testowa transkrypcja.")

    def test_upload_rejects_bad_name_and_empty_prompt(self):
        self.assertEqual(self._upload(name="../evil").status_code, 400)
        self.assertEqual(self._upload(name="a|b").status_code, 400)
        self.assertEqual(self._upload(prompt="  ").status_code, 400)

    def test_upload_rejects_unconvertible_audio(self):
        response = self.client.post(
            "/voices",
            data={"name": "zly", "prompt": "Tekst."},
            files={"audio": ("junk.wav", b"not audio at all", "audio/wav")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("ffmpeg", response.json()["detail"])

    def test_voice_audio_and_delete(self):
        self._upload()
        audio = self.client.get("/voices/nowy/audio")
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio.headers["content-type"], "audio/wav")

        self.assertEqual(self.client.get("/voices/brak/audio").status_code, 404)
        self.assertEqual(self.client.delete("/voices/brak").status_code, 404)

        deleted = self.client.delete("/voices/nowy")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["voices"], [])
        self.assertFalse((Path(self.temp.name) / "nowy").exists())

    def test_voice_endpoints_require_token_when_configured(self):
        with patch.dict(os.environ, {"DOTSTTS_API_TOKEN": "sekret"}):
            self.assertEqual(self._upload().status_code, 401)
            self.assertEqual(self.client.delete("/voices/x").status_code, 401)
            self.assertEqual(self.client.get("/voices/x/audio").status_code, 401)
            # listing stays open, like /health
            self.assertEqual(self.client.get("/voices").status_code, 200)


if __name__ == "__main__":
    unittest.main()
