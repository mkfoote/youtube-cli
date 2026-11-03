import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from youtube_cli.app import redirected_tui_stderr


class AppTests(unittest.TestCase):
    def test_tui_stderr_redirects_file_descriptor_two(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name

        old_value = os.environ.get("YOUTUBE_CLI_LOG")
        os.environ["YOUTUBE_CLI_LOG"] = path
        try:
            with redirected_tui_stderr(verbose=True):
                os.write(2, b"hidden from terminal\n")
        finally:
            if old_value is None:
                os.environ.pop("YOUTUBE_CLI_LOG", None)
            else:
                os.environ["YOUTUBE_CLI_LOG"] = old_value

        self.assertEqual(Path(path).read_text(), "hidden from terminal\n")
        os.unlink(path)


if __name__ == "__main__":
    unittest.main()
