from __future__ import annotations

import curses
import threading
from typing import Any

from .models import SearchResult, Track
from .prefetch import MixPrefetcher
from .youtube import YoutubeMixClient


class SearchController:
    def __init__(self, client: YoutubeMixClient, prefetcher: MixPrefetcher) -> None:
        self.client = client
        self.prefetcher = prefetcher
        self.mode = "queue"
        self.query = ""
        self.results: list[SearchResult] = []
        self.selected_index = 0
        self.status = ""
        self.searching = False
        self.adding = False
        self.result_states: dict[str, str] = {}
        self.jump_ready: Track | None = None
        self.lock = threading.Lock()

    def open(self) -> str:
        with self.lock:
            self.mode = "input"
            self.query = ""
            self.status = "search"
        return "search"

    def close(self) -> str:
        with self.lock:
            self.mode = "queue"
            self.status = ""
        return "queue"

    def handle_key(self, key: int) -> str | None:
        with self.lock:
            mode = self.mode

        if mode == "input":
            return self._handle_input_key(key)
        if mode == "results":
            return self._handle_results_key(key)
        return None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "mode": self.mode,
                "query": self.query,
                "results": list(self.results),
                "selected_index": self.selected_index,
                "status": self.status,
                "searching": self.searching,
                "adding": self.adding,
                "result_states": dict(self.result_states),
            }

    def _handle_input_key(self, key: int) -> str | None:
        if key in (27,):
            return self.close()
        if key in (curses.KEY_ENTER, 10, 13):
            with self.lock:
                query = self.query.strip()
            if query:
                self._start_search(query)
                return f"searching {query}"
            return "empty search"
        if key in (curses.KEY_BACKSPACE, 127, 8):
            with self.lock:
                self.query = self.query[:-1]
            return None
        if 32 <= key <= 126:
            with self.lock:
                self.query += chr(key)
            return None
        return None

    def _handle_results_key(self, key: int) -> str | None:
        if key in (27,):
            return self.close()
        if key == curses.KEY_UP:
            with self.lock:
                self.selected_index = max(0, self.selected_index - 1)
            return None
        if key == curses.KEY_DOWN:
            with self.lock:
                if self.results:
                    self.selected_index = min(len(self.results) - 1, self.selected_index + 1)
            return None
        if key in (curses.KEY_ENTER, 10, 13, ord("a"), ord("A")):
            return self._start_add_selected(play_next=False, jump_now=False)
        if key in (ord("n"), ord("N")):
            return self._start_add_selected(play_next=True, jump_now=False)
        if key in (ord("j"), ord("J")):
            return self._start_add_selected(play_next=False, jump_now=True)
        return None

    def _start_search(self, query: str) -> None:
        with self.lock:
            if self.searching:
                return
            self.searching = True
            self.mode = "results"
            self.results = []
            self.selected_index = 0
            self.status = f"searching {query}"

        thread = threading.Thread(
            target=self._search_worker,
            args=(query,),
            name="manual-search",
            daemon=True,
        )
        thread.start()

    def _search_worker(self, query: str) -> None:
        try:
            results = self.client.search(query, limit=10)
            status = f"{len(results)} results"
        except Exception as exc:
            results = []
            status = f"search failed: {exc}"

        with self.lock:
            self.results = results
            self.selected_index = 0
            self.result_states = {}
            self.status = status
            self.searching = False

    def _start_add_selected(self, *, play_next: bool, jump_now: bool) -> str | None:
        with self.lock:
            if self.adding:
                return "already adding"
            if not self.results:
                return "no search results"
            selected = self.results[self.selected_index]
            self.adding = True
            self.result_states[selected.webpage_url] = "resolving"
            action = "playing now" if jump_now else "adding next" if play_next else "adding"
            self.status = f"{action} {selected.label}"

        if not jump_now:
            added_pending = self.prefetcher.playlist.add_pending(
                title=selected.title,
                artist=selected.artist,
                webpage_url=selected.webpage_url,
                stop_event=self.prefetcher.stop_event,
                play_next=play_next,
                wait_for_space=False,
            )
            if not added_pending:
                with self.lock:
                    self.adding = False
                    self.result_states[selected.webpage_url] = "duplicate"
                    self.status = f"not added {selected.label}"
                return f"not added {selected.label}"

        thread = threading.Thread(
            target=self._add_worker,
            args=(selected, jump_now),
            name="manual-add",
            daemon=True,
        )
        thread.start()
        return self.status

    def _add_worker(self, selected: SearchResult, jump_now: bool) -> None:
        try:
            track = self.client.resolve(selected.webpage_url)
            if jump_now:
                with self.lock:
                    self.jump_ready = track
                added = True
            else:
                added = self.prefetcher.playlist.resolve_pending(selected.webpage_url, track)
            state = "added" if added else "failed"
            status = f"ready {track.label}" if jump_now else f"added {track.label}" if added else f"not added {track.label}"
        except Exception as exc:
            state = "failed"
            status = f"add failed: {exc}"
            if not jump_now:
                self.prefetcher.playlist.fail_pending(selected.webpage_url, selected.label)

        with self.lock:
            self.adding = False
            self.result_states[selected.webpage_url] = state
            self.status = status

    def consume_jump(self) -> Track | None:
        with self.lock:
            track = self.jump_ready
            self.jump_ready = None
            return track
