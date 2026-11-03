import sys
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from youtube_cli.models import Track
from youtube_cli.youtube import YoutubeMixClient


class YoutubeSearchTests(unittest.TestCase):
    def test_search_uses_flat_extraction_results(self) -> None:
        client = YoutubeMixClient.__new__(YoutubeMixClient)
        client.ydl_opts = {}
        client.verbose = False

        def extract_flat(_query):
            return {
                "entries": [
                    {
                        "id": "abc123def45",
                        "title": "Artist - Song",
                        "duration": "210",
                    }
                ]
            }

        client._extract_flat = extract_flat

        results = client.search("artist song", limit=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].label, "Artist - Song")
        self.assertEqual(results[0].duration, 210)
        self.assertEqual(results[0].webpage_url, "https://www.youtube.com/watch?v=abc123def45")

    def test_player_stderr_is_suppressed_even_when_verbose(self) -> None:
        client = YoutubeMixClient.__new__(YoutubeMixClient)
        client.player_cmd = ["mpv"]
        client.verbose = True
        track = Track(
            title="Song",
            artist="Artist",
            url="https://stream.example",
            webpage_url="https://youtube.example/watch?v=123",
        )

        with patch("youtube_cli.youtube.subprocess.Popen") as popen:
            client.start_player(track)

        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
