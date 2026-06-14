from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from typing import Any, Iterable

from .models import MixCandidate, RecommendedSong, SearchResult, Track
from .playback import PlayerProcess, stop_process
from .text import infer_artist_from_title

try:
    import yt_dlp
except ImportError:  # pragma: no cover - exercised by users before install
    yt_dlp = None

YOUTUBE_WATCH_PREFIX = "https://www.youtube.com/watch?v="
YOUTUBE_BASE = "https://www.youtube.com"


class YoutubeMixClient:
    def __init__(self, *, player: str | None, verbose: bool = False) -> None:
        if yt_dlp is None:
            raise RuntimeError(
                "yt-dlp is not installed. Install dependencies with: python -m pip install -e ."
            )

        self.player_cmd = shlex.split(player) if player else [self._find_player()]
        if not self.player_cmd:
            raise RuntimeError("Player command cannot be empty.")
        self.verbose = verbose
        self.seen: set[str] = set()
        self.ydl_opts = {
            "format": "bestaudio/best",
            "quiet": not verbose,
            "no_warnings": not verbose,
            "default_search": "ytsearch",
            "extract_flat": False,
            "noplaylist": True,
        }

    def _find_player(self) -> str:
        for candidate in ("ffplay", "mpv"):
            path = shutil.which(candidate)
            if path:
                return path
        raise RuntimeError("No supported player found. Install ffplay/FFmpeg or mpv.")

    def search_first(self, query: str) -> Track:
        info = self._extract(f"ytsearch1:{query}")
        entries = info.get("entries") or []
        if not entries:
            raise RuntimeError(f"No YouTube result found for: {query}")
        return self._track_from_info(entries[0])

    def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        info = self._extract(f"ytsearch{limit}:{query}")
        results: list[SearchResult] = []
        for entry in info.get("entries") or []:
            result = self._search_result_from_info(entry)
            if result:
                results.append(result)
        return results

    def resolve(self, webpage_url: str) -> Track:
        return self._track_from_info(self._extract(webpage_url))

    def resolve_recommended_song(self, song: RecommendedSong) -> Track | None:
        queries = [
            f"{song.artist} {song.title} official audio",
            f"{song.artist} {song.title}",
        ]
        for query in queries:
            try:
                results = self.search(query, limit=3)
            except Exception as exc:
                if self.verbose:
                    print(f"Recommendation search failed query={query!r}: {exc}", file=sys.stderr)
                continue
            for result in results:
                try:
                    return self.resolve(result.webpage_url)
                except Exception as exc:
                    if self.verbose:
                        print(f"Recommendation result failed {result.label!r}: {exc}", file=sys.stderr)
        return None

    def mix_candidates(self, track: Track) -> Iterable[MixCandidate]:
        try:
            info = self._extract(track.webpage_url)
        except Exception as exc:
            if self.verbose:
                print(f"Could not inspect related videos: {exc}", file=sys.stderr)
        else:
            for item in self._related_urls(info):
                yield item

        for item in self._search_mix_urls(track):
            yield item

    def play(self, track: Track) -> bool:
        print(f"\nNow playing: {track.label}", flush=True)
        process = self.start_player(track)
        try:
            return process.wait() == 0
        except KeyboardInterrupt:
            stop_process(process)
            raise

    def start_player(self, track: Track) -> PlayerProcess:
        player_name = self._player_name()
        if player_name == "ffplay":
            return self._start_ffplay_with_ytdlp(track)
        if player_name == "mpv":
            return PlayerProcess(
                subprocess.Popen(
                    self._player_command(track.webpage_url),
                    stdout=subprocess.DEVNULL,
                    stderr=None if self.verbose else subprocess.DEVNULL,
                )
            )
        return PlayerProcess(
            subprocess.Popen(
                self._player_command(track.url),
                stdout=subprocess.DEVNULL,
                stderr=None if self.verbose else subprocess.DEVNULL,
            )
        )

    def _start_ffplay_with_ytdlp(self, track: Track) -> PlayerProcess:
        downloader = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "yt_dlp",
                "--no-playlist",
                "--quiet",
                "--no-warnings",
                "--retries",
                "10",
                "--fragment-retries",
                "10",
                "-f",
                "bestaudio/best",
                "-o",
                "-",
                track.webpage_url,
            ],
            stdout=subprocess.PIPE,
            stderr=None if self.verbose else subprocess.DEVNULL,
        )
        player = subprocess.Popen(
            self._ffplay_pipe_command(),
            stdin=downloader.stdout,
            stdout=subprocess.DEVNULL,
            stderr=None if self.verbose else subprocess.DEVNULL,
        )
        if downloader.stdout:
            downloader.stdout.close()
        return PlayerProcess(player, [downloader])

    def _extract(self, url_or_query: str) -> dict[str, Any]:
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            return ydl.extract_info(url_or_query, download=False)

    def _track_from_info(self, info: dict[str, Any]) -> Track:
        webpage_url = info.get("webpage_url") or self._watch_url(info)
        stream_url = info.get("url")

        if not stream_url and webpage_url:
            resolved = self._extract(webpage_url)
            stream_url = resolved.get("url")
            info = resolved

        if not webpage_url or not stream_url:
            raise RuntimeError("yt-dlp did not return a playable stream for this result.")

        title = info.get("title") or "Unknown title"
        artist = info.get("artist")
        if not artist:
            inferred_artist, inferred_title = infer_artist_from_title(title)
            artist = inferred_artist
            title = inferred_title
        duration = info.get("duration")
        self.seen.add(webpage_url)

        return Track(
            title=title,
            artist=artist,
            duration=duration if isinstance(duration, int) else None,
            url=stream_url,
            webpage_url=webpage_url,
        )

    def _search_result_from_info(self, info: dict[str, Any]) -> SearchResult | None:
        webpage_url = info.get("webpage_url") or self._watch_url(info)
        if not webpage_url:
            return None

        title = info.get("title") or "Unknown title"
        artist = info.get("artist")
        if not artist:
            inferred_artist, inferred_title = infer_artist_from_title(title)
            artist = inferred_artist
            title = inferred_title
        duration = info.get("duration")
        return SearchResult(
            title=title,
            artist=artist,
            duration=duration if isinstance(duration, int) else None,
            webpage_url=webpage_url,
        )

    def _related_urls(self, info: dict[str, Any]) -> Iterable[MixCandidate]:
        related = info.get("related_videos") or []

        for rank, item in enumerate(related):
            url = item.get("webpage_url") or item.get("url")
            video_id = item.get("id")
            if video_id and not url:
                url = f"{YOUTUBE_WATCH_PREFIX}{video_id}"
            if isinstance(url, str):
                normalized = self._normalize_video_url(url)
                if normalized:
                    yield MixCandidate(url=normalized, source="related", source_rank=rank)

    def _search_mix_urls(self, track: Track) -> Iterable[MixCandidate]:
        seeds = [
            f"songs like {track.label}",
            f"{track.label} radio song",
            f"songs similar to {track.label}",
            f"{track.title} playlist similar songs",
        ]
        if track.artist:
            seeds.extend(
                [
                    f"artists like {track.artist}",
                    f"{track.artist} similar songs official audio",
                    f"{track.artist} fans also like songs",
                ]
            )

        for seed in seeds:
            try:
                info = self._extract(f"ytsearch12:{seed}")
            except Exception as exc:
                if self.verbose:
                    print(f"Search seed failed {seed!r}: {exc}", file=sys.stderr)
                continue
            entries = list(info.get("entries") or [])
            for rank, entry in enumerate(entries):
                url = entry.get("webpage_url") or self._watch_url(entry)
                normalized = self._normalize_video_url(url) if url else None
                if normalized:
                    yield MixCandidate(
                        url=normalized,
                        source="search",
                        source_rank=rank,
                        seed_query=seed,
                    )

    def _watch_url(self, info: dict[str, Any]) -> str | None:
        video_id = info.get("id")
        if not video_id:
            return None
        return f"{YOUTUBE_WATCH_PREFIX}{video_id}"

    def _normalize_video_url(self, url: str) -> str | None:
        if url.startswith("http://") or url.startswith("https://"):
            return url
        if url.startswith("/"):
            return f"{YOUTUBE_BASE}{url}"
        if len(url) == 11 and "/" not in url and " " not in url:
            return f"{YOUTUBE_WATCH_PREFIX}{url}"
        return None

    def _player_command(self, stream_url: str) -> list[str]:
        player_name = self._player_name()
        if player_name == "ffplay":
            return [
                *self.player_cmd,
                "-nodisp",
                "-autoexit",
                "-hide_banner",
                "-loglevel",
                "error",
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "10",
                stream_url,
            ]
        if player_name == "mpv":
            return [*self.player_cmd, "--no-video", "--ytdl=yes", "--really-quiet", stream_url]
        return [*self.player_cmd, stream_url]

    def _ffplay_pipe_command(self) -> list[str]:
        return [
            *self.player_cmd,
            "-nodisp",
            "-autoexit",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
        ]

    def _player_name(self) -> str:
        return self.player_cmd[0].rsplit("/", 1)[-1]
