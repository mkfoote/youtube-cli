import curses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from youtube_cli.view import TerminalUI


class ViewTests(unittest.TestCase):
    def setUp(self) -> None:
        ui = TerminalUI.__new__(TerminalUI)
        self.ui = ui

    def test_h_and_left_arrow_restart_current_song(self) -> None:
        for key in (ord("h"), ord("H"), curses.KEY_LEFT):
            with self.subTest(key=key):
                self.assertEqual(self.ui.translate_key(key), "restart")

    def test_j_and_down_arrow_move_queue_selection_down(self) -> None:
        for key in (ord("j"), ord("J"), curses.KEY_DOWN):
            with self.subTest(key=key):
                self.assertEqual(self.ui.translate_key(key), "down")

    def test_k_and_up_arrow_move_queue_selection_up(self) -> None:
        for key in (ord("k"), ord("K"), curses.KEY_UP):
            with self.subTest(key=key):
                self.assertEqual(self.ui.translate_key(key), "up")

    def test_l_and_right_arrow_skip_current_song(self) -> None:
        for key in (ord("l"), ord("L"), curses.KEY_RIGHT):
            with self.subTest(key=key):
                self.assertEqual(self.ui.translate_key(key), "skip")


if __name__ == "__main__":
    unittest.main()
