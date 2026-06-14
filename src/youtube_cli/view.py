from __future__ import annotations

import curses
import time
from typing import Any

from .models import Track


class TerminalUI:
    def __init__(self, screen: curses.window) -> None:
        self.screen = screen
        self.selected_index = 0
        self.scroll_offset = 0
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        curses.use_default_colors()
        self.screen.nodelay(True)
        self.screen.keypad(True)

    def read_raw_key(self) -> int:
        return self.screen.getch()

    def read_key(self) -> str | None:
        key = self.read_raw_key()
        return self.translate_key(key)

    def translate_key(self, key: int) -> str | None:
        if key == -1:
            return None
        if key in (ord("q"), ord("Q")):
            return "quit"
        if key in (ord("s"), ord("S"), curses.KEY_RIGHT):
            return "skip"
        if key == ord(" "):
            return "pause"
        if key in (curses.KEY_ENTER, 10, 13):
            return "jump"
        if key == curses.KEY_UP:
            return "up"
        if key == curses.KEY_DOWN:
            return "down"
        if key in (curses.KEY_DC, 127, 8):
            return "delete"
        if key == ord("/"):
            return "search"
        return None

    def move_selection(self, delta: int, queue_length: int) -> None:
        if queue_length <= 0:
            self.selected_index = 0
            self.scroll_offset = 0
            return
        self.selected_index = min(
            queue_length - 1,
            max(0, self.selected_index + delta),
        )

    def selected_queue_index(self, queue_length: int) -> int | None:
        if queue_length <= 0:
            return None
        self.selected_index = min(self.selected_index, queue_length - 1)
        return self.selected_index

    def draw(
        self,
        *,
        current: Track | None,
        queue_tracks: list[Track],
        elapsed: float,
        status: str,
        plays: int,
        search_state: dict[str, Any] | None = None,
    ) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 8 or width < 36:
            self._add_line(0, 0, "Resize terminal: at least 36x8")
            self.screen.refresh()
            return

        self._add_line(0, 0, "youtube-cli", curses.A_BOLD)
        controls = "enter jump  del remove  space pause  s skip  q quit"
        if width >= 92:
            controls = "up/dn select  enter jump  del remove  space pause  s skip  q quit"
        self._add_line(0, max(12, width - len(controls)), controls, curses.A_DIM)
        self._hline(1, width)

        search_height = self._draw_search(search_state, width)
        queue_top = 3 + search_height
        queue_bottom = max(queue_top, height - 5)
        visible_count = max(0, queue_bottom - queue_top)
        self._clamp_scroll(len(queue_tracks), visible_count)
        self._add_line(2, 0, f"Queue ({len(queue_tracks)})", curses.A_BOLD)

        visible = queue_tracks[self.scroll_offset : self.scroll_offset + visible_count]
        if visible:
            for row, track in enumerate(visible):
                queue_index = self.scroll_offset + row
                marker = ">" if queue_index == self.selected_index else " "
                label = f"{marker} {queue_index + 1:>2}. {track.label}"
                attr = curses.A_REVERSE if queue_index == self.selected_index else 0
                self._add_line(queue_top + row, 0, self._fit(label, width), attr)
        else:
            self._add_line(queue_top, 0, "Finding the next tracks...", curses.A_DIM)

        bottom = height - 3
        self._hline(bottom - 1, width)
        now = current.label if current else "Loading..."
        self._add_line(bottom, 0, self._fit(f"Now playing: {now}", width), curses.A_BOLD)

        duration = current.duration if current else None
        bar = self._progress_bar(elapsed, duration, max(10, width - 18))
        time_text = f"{format_time(int(elapsed))}/{format_time(duration)}"
        self._add_line(bottom + 1, 0, self._fit(f"{bar} {time_text}", width))

        footer = f"{status} | played {plays}"
        self._add_line(bottom + 2, 0, self._fit(footer, width), curses.A_DIM)
        self.screen.refresh()

    def _draw_search(self, search_state: dict[str, Any] | None, width: int) -> int:
        if not search_state or search_state.get("mode") == "queue":
            self._add_line(2, max(0, width - 16), "/ search", curses.A_DIM)
            return 0

        mode = search_state.get("mode")
        query = search_state.get("query", "")
        status = search_state.get("status", "")
        results = search_state.get("results") or []
        selected = search_state.get("selected_index", 0)

        self._add_line(2, 0, self._fit(f"Search: {query}", width), curses.A_BOLD)
        self._add_line(2, max(0, width - len(status)), status, curses.A_DIM)

        if mode == "input":
            self._add_line(3, 0, self._fit("type search, enter submit, esc cancel", width), curses.A_DIM)
            return 2

        max_results = 4
        start = min(max(0, selected - max_results + 1), max(0, len(results) - max_results))
        visible = results[start : start + max_results]
        for row, result in enumerate(visible):
            result_index = start + row
            marker = ">" if result_index == selected else " "
            attr = curses.A_REVERSE if result_index == selected else 0
            self._add_line(
                3 + row,
                0,
                self._fit(f"{marker} {result_index + 1}. {result.label}", width),
                attr,
            )

        if not results:
            self._add_line(3, 0, "No results yet", curses.A_DIM)
            return 2

        return 1 + min(max_results, len(results))

    def _clamp_scroll(self, queue_length: int, visible_count: int) -> None:
        if queue_length <= 0 or visible_count <= 0:
            self.selected_index = 0
            self.scroll_offset = 0
            return
        self.selected_index = min(self.selected_index, queue_length - 1)
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        if self.selected_index >= self.scroll_offset + visible_count:
            self.scroll_offset = self.selected_index - visible_count + 1
        max_offset = max(0, queue_length - visible_count)
        self.scroll_offset = min(max(0, self.scroll_offset), max_offset)

    def _progress_bar(self, elapsed: float, duration: int | None, width: int) -> str:
        if duration and duration > 0:
            filled = min(width, max(0, int(width * (elapsed / duration))))
            return "[" + "#" * filled + "-" * (width - filled) + "]"
        pulse = int(time.monotonic() * 8) % width
        chars = ["-"] * width
        chars[pulse] = "#"
        return "[" + "".join(chars) + "]"

    def _fit(self, text: str, width: int) -> str:
        if len(text) <= width:
            return text
        if width <= 1:
            return text[:width]
        return text[: width - 3] + "..." if width > 3 else text[:width]

    def _hline(self, row: int, width: int) -> None:
        if 0 <= row < self.screen.getmaxyx()[0]:
            self.screen.hline(row, 0, curses.ACS_HLINE, width)

    def _add_line(self, row: int, col: int, text: str, attr: int = 0) -> None:
        height, width = self.screen.getmaxyx()
        if row < 0 or row >= height or col >= width:
            return
        safe = self._fit(text, width - col)
        try:
            self.screen.addstr(row, col, safe, attr)
        except curses.error:
            pass


def format_time(seconds: int | None) -> str:
    if seconds is None:
        return "--:--"
    minutes, remaining = divmod(max(0, seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remaining:02d}"
    return f"{minutes}:{remaining:02d}"
