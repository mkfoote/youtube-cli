from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .text import normalize_song_text, normalize_title_key


@dataclass(frozen=True)
class Track:
    title: str
    url: str
    webpage_url: str
    artist: str | None = None
    duration: int | None = None

    @property
    def label(self) -> str:
        if self.artist and self.artist not in self.title:
            return f"{self.artist} - {self.title}"
        return self.title

    @property
    def fingerprint(self) -> str:
        artist = normalize_song_text(self.artist or "")
        title = normalize_title_key(self.title, self.artist)
        return f"{artist}|{title}"

    @property
    def title_key(self) -> str:
        return normalize_title_key(self.title, self.artist)

    @property
    def artist_key(self) -> str:
        return normalize_song_text(self.artist or "")


@dataclass(frozen=True)
class PlaybackResult:
    action: str
    track: Track | None = None


@dataclass(frozen=True)
class MixCandidate:
    url: str
    source: str
    source_rank: int
    seed_query: str | None = None


@dataclass(frozen=True)
class RecommendedSong:
    artist: str
    title: str
    source: str
    score: float
    year: int | None = None
    tags: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.artist} - {self.title}"

    @property
    def key(self) -> str:
        return f"{normalize_song_text(self.artist)}|{normalize_title_key(self.title, self.artist)}"


@dataclass(frozen=True)
class MusicMetadata:
    year: int | None = None
    tags: tuple[str, ...] = ()


class RecommendationProvider(Protocol):
    def recommendations(self, seed: Track, *, limit: int) -> list[RecommendedSong]:
        ...


@dataclass(frozen=True)
class SearchResult:
    title: str
    webpage_url: str
    artist: str | None = None
    duration: int | None = None

    @property
    def label(self) -> str:
        if self.artist and self.artist not in self.title:
            return f"{self.artist} - {self.title}"
        return self.title
