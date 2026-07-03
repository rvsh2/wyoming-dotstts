import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from dotstts_wyoming import server as http_server
from dotstts_wyoming.runtime_settings import load_settings, save_settings
from dotstts_wyoming.synthesizer import DotsTtsSynthesizer


class SettingsEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_file = Path(self.temp.name) / "settings.json"

        self._old_service = http_server.service
        self._old_path = http_server.settings_path
        http_server.service = DotsTtsSynthesizer(speaker_dir=self.temp.name)
        http_server.settings_path = self.settings_file
        self.addCleanup(self._restore)
        self.client = TestClient(http_server.app)

    def _restore(self):
        http_server.service = self._old_service
        http_server.settings_path = self._old_path

    def test_settings_open_without_configured_token(self):
        with patch.dict(os.environ, {"DOTSTTS_API_TOKEN": ""}):
            response = self.client.get("/settings")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"seed": None, "gain_db": 0.0})

    def test_settings_requires_token_when_configured(self):
        with patch.dict(os.environ, {"DOTSTTS_API_TOKEN": "sekret"}):
            self.assertEqual(self.client.get("/settings").status_code, 401)
            self.assertEqual(
                self.client.post("/settings", json={"gain_db": 6}).status_code, 401
            )
            self.assertEqual(
                self.client.post("/synthesize", json={"text": "x"}).status_code, 401
            )
            response = self.client.get("/settings", headers={"X-API-Token": "sekret"})
        self.assertEqual(response.status_code, 200)

    def test_post_settings_updates_and_persists(self):
        with patch.dict(os.environ, {"DOTSTTS_API_TOKEN": ""}):
            response = self.client.post("/settings", json={"seed": 42, "gain_db": 6.5})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"seed": 42, "gain_db": 6.5})
        self.assertEqual(http_server.service.seed, 42)
        self.assertEqual(http_server.service.gain_db, 6.5)
        self.assertEqual(
            json.loads(self.settings_file.read_text()), {"seed": 42, "gain_db": 6.5}
        )

    def test_post_null_seed_restores_random(self):
        http_server.service.seed = 42
        with patch.dict(os.environ, {"DOTSTTS_API_TOKEN": ""}):
            response = self.client.post("/settings", json={"seed": None})
        self.assertIsNone(response.json()["seed"])
        self.assertIsNone(http_server.service.seed)

    def test_post_partial_update_keeps_other_setting(self):
        http_server.service.seed = 42
        with patch.dict(os.environ, {"DOTSTTS_API_TOKEN": ""}):
            response = self.client.post("/settings", json={"gain_db": 3})
        self.assertEqual(response.json(), {"seed": 42, "gain_db": 3.0})

    def test_gain_out_of_range_rejected(self):
        with patch.dict(os.environ, {"DOTSTTS_API_TOKEN": ""}):
            self.assertEqual(
                self.client.post("/settings", json={"gain_db": 99}).status_code, 422
            )


class RuntimeSettingsFileTests(unittest.TestCase):
    def test_load_missing_file_returns_empty(self):
        self.assertEqual(load_settings("/nonexistent/settings.json"), {})

    def test_roundtrip_and_unknown_keys_dropped(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sub" / "settings.json"
            save_settings(path, {"seed": 1, "gain_db": 2.5, "bogus": True})
            self.assertEqual(load_settings(path), {"seed": 1, "gain_db": 2.5})

    def test_corrupt_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_settings(path), {})


if __name__ == "__main__":
    unittest.main()
