from __future__ import annotations

import curses
import threading
from typing import Any

from .models import SearchResult
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
        if key in (curses.KEY_ENTER, 10, 13):
            return self._start_add_selected()
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
            self.status = status
            self.searching = False

    def _start_add_selected(self) -> str | None:
        with self.lock:
            if self.adding:
                return "already adding"
            if not self.results:
                return "no search results"
            selected = self.results[self.selected_index]
            self.adding = True
            self.status = f"adding {selected.label}"

        thread = threading.Thread(
            target=self._add_worker,
            args=(selected,),
            name="manual-add",
            daemon=True,
        )
        thread.start()
        return f"adding {selected.label}"

    def _add_worker(self, selected: SearchResult) -> None:
        try:
            track = self.client.resolve(selected.webpage_url)
            added = self.prefetcher.playlist.add(
                track,
                stop_event=self.prefetcher.stop_event,
            )
            status = f"added {track.label}" if added else f"not added {track.label}"
        except Exception as exc:
            status = f"add failed: {exc}"

        with self.lock:
            self.adding = False
            self.status = status
