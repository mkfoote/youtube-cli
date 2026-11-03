import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from youtube_cli.config import (
    clear_lastfm_api_key,
    config_path,
    lastfm_api_key,
    lastfm_api_key_source,
    save_lastfm_api_key,
)
from youtube_cli.recommendations import build_recommendation_providers


class ConfigTests(unittest.TestCase):
    def test_config_path_uses_xdg_config_home(self) -> None:
        path = config_path({"XDG_CONFIG_HOME": "/tmp/example-config"})

        self.assertEqual(path, Path("/tmp/example-config/youtube-cli/config.ini"))

    def test_config_path_allows_explicit_override(self) -> None:
        path = config_path(
            {
                "XDG_CONFIG_HOME": "/tmp/ignored",
                "YOUTUBE_CLI_CONFIG_FILE": "/tmp/custom.ini",
            }
        )

        self.assertEqual(path, Path("/tmp/custom.ini"))

    def test_saved_key_can_be_loaded_and_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            env = {"YOUTUBE_CLI_CONFIG_FILE": str(path)}

            save_lastfm_api_key(" saved-key ", path)

            self.assertEqual(lastfm_api_key(env), "saved-key")
            self.assertEqual(lastfm_api_key_source(env), "config file")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertTrue(clear_lastfm_api_key(path))
            self.assertEqual(lastfm_api_key(env), "")
            self.assertFalse(clear_lastfm_api_key(path))

    def test_environment_key_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            save_lastfm_api_key("saved-key", path)
            env = {
                "YOUTUBE_CLI_CONFIG_FILE": str(path),
                "LASTFM_API_KEY": "environment-key",
            }

            self.assertEqual(lastfm_api_key(env), "environment-key")
            self.assertEqual(lastfm_api_key_source(env), "environment")

    def test_recommender_uses_saved_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            save_lastfm_api_key("saved-key", path)
            env = {
                "YOUTUBE_CLI_CONFIG_FILE": str(path),
                "YOUTUBE_CLI_RECOMMENDER": "lastfm",
            }

            with patch.dict(os.environ, env, clear=True):
                providers = build_recommendation_providers(verbose=False)

            self.assertEqual(len(providers), 1)
            self.assertEqual(providers[0].api_key, "saved-key")


if __name__ == "__main__":
    unittest.main()
