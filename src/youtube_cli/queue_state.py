from __future__ import annotations

import threading

from .models import Track
from .text import song_keys_match, title_key_is_distinctive


class PlaylistState:
    def __init__(self, *, max_size: int) -> None:
        self.max_size = max_size
        self.items: list[Track] = []
        self.fingerprints: set[str] = set()
        self.title_keys: set[str] = set()
        self.lock = threading.Condition()

    def add(
        self,
        track: Track,
        *,
        stop_event: threading.Event,
    ) -> bool:
        with self.lock:
            if self._is_duplicate_locked(track):
                return False
            while len(self.items) >= self.max_size and not stop_event.is_set():
                self.lock.wait(timeout=0.5)
            if stop_event.is_set() or self._is_duplicate_locked(track):
                return False
            self.items.append(track)
            self._remember_locked(track)
            self.lock.notify_all()
            return True

    def add_pending(
        self,
        *,
        title: str,
        webpage_url: str,
        artist: str | None,
        stop_event: threading.Event,
        play_next: bool = False,
        wait_for_space: bool = True,
    ) -> bool:
        pending = Track(
            title=f"Resolving: {title}",
            artist=artist,
            duration=None,
            url="",
            webpage_url=webpage_url,
        )
        with self.lock:
            if self._is_duplicate_locked(pending):
                return False
            if len(self.items) >= self.max_size and not wait_for_space:
                self.items.pop()
            while len(self.items) >= self.max_size and not stop_event.is_set():
                self.lock.wait(timeout=0.5)
            if stop_event.is_set() or self._is_duplicate_locked(pending):
                return False
            if play_next:
                self.items.insert(0, pending)
            else:
                self.items.append(pending)
            self._remember_locked(pending)
            self.lock.notify_all()
            return True

    def resolve_pending(self, webpage_url: str, track: Track) -> bool:
        with self.lock:
            for index, item in enumerate(self.items):
                if item.webpage_url == webpage_url and not item.url:
                    self.items[index] = track
                    self._remember_locked(track)
                    self.lock.notify_all()
                    return True
            return False

    def fail_pending(self, webpage_url: str, label: str) -> None:
        with self.lock:
            for index, item in enumerate(self.items):
                if item.webpage_url == webpage_url and not item.url:
                    self.items[index] = Track(
                        title=f"Failed: {label}",
                        artist=item.artist,
                        duration=None,
                        url="",
                        webpage_url=webpage_url,
                    )
                    self.lock.notify_all()
                    return

    def remember(self, track: Track) -> None:
        with self.lock:
            self._remember_locked(track)

    def pop_next(self, *, stop_event: threading.Event) -> Track:
        with self.lock:
            while not stop_event.is_set():
                self._discard_failed_locked()
                if self.items and self.items[0].url:
                    break
                self.lock.wait(timeout=0.5)
            if stop_event.is_set():
                raise KeyboardInterrupt
            track = self.items.pop(0)
            self.lock.notify_all()
            return track

    def pop_next_nowait(self) -> Track | None:
        with self.lock:
            self._discard_failed_locked()
            if not self.items or not self.items[0].url:
                return None
            track = self.items.pop(0)
            self.lock.notify_all()
            return track

    def remove(self, index: int) -> Track | None:
        with self.lock:
            if index < 0 or index >= len(self.items):
                return None
            track = self.items.pop(index)
            self.lock.notify_all()
            return track

    def snapshot(self) -> list[Track]:
        with self.lock:
            return list(self.items)

    def qsize(self) -> int:
        with self.lock:
            return len(self.items)

    def _is_duplicate_locked(self, track: Track) -> bool:
        if track.fingerprint in self.fingerprints:
            return True
        if not title_key_is_distinctive(track.title_key):
            return False
        if track.title_key in self.title_keys:
            return True
        return any(song_keys_match(track.title_key, existing) for existing in self.title_keys)

    def _remember_locked(self, track: Track) -> None:
        self.fingerprints.add(track.fingerprint)
        if title_key_is_distinctive(track.title_key):
            self.title_keys.add(track.title_key)

    def _discard_failed_locked(self) -> None:
        while self.items and not self.items[0].url and self.items[0].title.startswith("Failed:"):
            self.items.pop(0)
            self.lock.notify_all()
