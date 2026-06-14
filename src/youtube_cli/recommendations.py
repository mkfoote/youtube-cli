from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any, Callable, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import MusicMetadata, RecommendationProvider, RecommendedSong, Track
from .text import infer_artist_from_title, normalize_song_text, normalize_title_key

METADATA_ENRICH_LIMIT = 16


def fetch_json(base_url: str, params: dict[str, str | int | float]) -> dict[str, Any]:
    url = f"{base_url}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "youtube-cli/0.1"})
    with urlopen(request, timeout=10) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    return data if isinstance(data, dict) else {}


def seed_artist_title(seed: Track) -> tuple[str | None, str]:
    if seed.artist:
        return seed.artist, seed.title
    artist, title = infer_artist_from_title(seed.title)
    return artist, title


def dedupe_recommendations(songs: Iterable[RecommendedSong], *, limit: int) -> list[RecommendedSong]:
    seen: set[str] = set()
    result: list[RecommendedSong] = []
    for song in sorted(songs, key=lambda item: item.score, reverse=True):
        if not song.artist or not song.title:
            continue
        if song.key in seen:
            continue
        seen.add(song.key)
        result.append(song)
        if len(result) >= limit:
            break
    return result


class LastFmRecommendationProvider:
    API_URL = "https://ws.audioscrobbler.com/2.0/"

    def __init__(
        self,
        api_key: str,
        *,
        fetcher: JsonFetcher = fetch_json,
        verbose: bool = False,
    ) -> None:
        self.api_key = api_key
        self.fetcher = fetcher
        self.verbose = verbose

    def recommendations(self, seed: Track, *, limit: int) -> list[RecommendedSong]:
        artist, title = seed_artist_title(seed)
        if not artist or not title:
            return []

        songs: list[RecommendedSong] = []
        songs.extend(self._similar_tracks(artist, title, limit=limit))
        similar_artists = self._similar_artists(artist, limit=6)
        for artist_name, artist_score in similar_artists:
            songs.extend(
                self._artist_top_tracks(
                    artist_name,
                    limit=4,
                    score_scale=max(0.2, artist_score),
                )
            )
        return dedupe_recommendations(songs, limit=limit)

    def _request(self, method: str, **params: str | int | float) -> dict[str, Any]:
        request_params: dict[str, str | int | float] = {
            "method": method,
            "api_key": self.api_key,
            "format": "json",
        }
        request_params.update(params)
        try:
            return self.fetcher(self.API_URL, request_params)
        except Exception as exc:
            if self.verbose:
                print(f"Last.fm request failed method={method}: {exc}", file=sys.stderr)
            return {}

    def _similar_tracks(self, artist: str, title: str, *, limit: int) -> list[RecommendedSong]:
        data = self._request(
            "track.getsimilar",
            artist=artist,
            track=title,
            autocorrect=1,
            limit=limit,
        )
        tracks = data.get("similartracks", {}).get("track", [])
        if isinstance(tracks, dict):
            tracks = [tracks]
        result: list[RecommendedSong] = []
        for index, item in enumerate(tracks if isinstance(tracks, list) else []):
            song = self._song_from_lastfm_track(item, source="lastfm-track", base_score=100 - index)
            if song:
                result.append(song)
        return result

    def _similar_artists(self, artist: str, *, limit: int) -> list[tuple[str, float]]:
        data = self._request("artist.getsimilar", artist=artist, autocorrect=1, limit=limit)
        artists = data.get("similarartists", {}).get("artist", [])
        if isinstance(artists, dict):
            artists = [artists]
        result: list[tuple[str, float]] = []
        for item in artists if isinstance(artists, list) else []:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            result.append((name.strip(), parse_float(item.get("match"), default=0.5)))
        return result

    def _artist_top_tracks(
        self,
        artist: str,
        *,
        limit: int,
        score_scale: float,
    ) -> list[RecommendedSong]:
        data = self._request("artist.gettoptracks", artist=artist, autocorrect=1, limit=limit)
        tracks = data.get("toptracks", {}).get("track", [])
        if isinstance(tracks, dict):
            tracks = [tracks]
        result: list[RecommendedSong] = []
        for index, item in enumerate(tracks if isinstance(tracks, list) else []):
            song = self._song_from_lastfm_track(
                item,
                source="lastfm-artist",
                base_score=(72 - index) * score_scale,
                fallback_artist=artist,
            )
            if song:
                result.append(song)
        return result

    def _song_from_lastfm_track(
        self,
        item: Any,
        *,
        source: str,
        base_score: float,
        fallback_artist: str | None = None,
    ) -> RecommendedSong | None:
        if not isinstance(item, dict):
            return None
        title = item.get("name")
        artist = item.get("artist")
        if isinstance(artist, dict):
            artist = artist.get("name")
        if not isinstance(artist, str) or not artist.strip():
            artist = fallback_artist
        if not isinstance(title, str) or not title.strip() or not artist:
            return None
        match_score = parse_float(item.get("match"), default=1.0)
        return RecommendedSong(
            artist=artist.strip(),
            title=title.strip(),
            source=source,
            score=base_score + match_score,
        )


class MusicBrainzEnricher:
    API_URL = "https://musicbrainz.org/ws/2/recording/"

    def __init__(
        self,
        *,
        fetcher: JsonFetcher = fetch_json,
        verbose: bool = False,
        pause_seconds: float = 1.0,
    ) -> None:
        self.fetcher = fetcher
        self.verbose = verbose
        self.pause_seconds = pause_seconds
        self.cache: dict[tuple[str, str], MusicMetadata] = {}
        self.last_request_at = 0.0

    def enrich(self, seed: Track, songs: list[RecommendedSong]) -> list[RecommendedSong]:
        seed_artist, seed_title = seed_artist_title(seed)
        if not seed_artist:
            return songs
        seed_metadata = self.lookup(seed_artist, seed_title)
        seed_year = seed_metadata.year
        seed_tags = set(seed_metadata.tags)
        if seed_year is None and not seed_tags:
            return songs

        enriched: list[RecommendedSong] = []
        for song in songs:
            metadata = self.lookup(song.artist, song.title)
            score = song.score
            if seed_year is not None and metadata.year is not None:
                year_distance = abs(seed_year - metadata.year)
                if year_distance <= 7:
                    score += 18 - year_distance
                elif year_distance > 15:
                    score -= 6
            if seed_tags and metadata.tags:
                overlap = seed_tags & set(metadata.tags)
                score += min(12, len(overlap) * 4)
            enriched.append(
                RecommendedSong(
                    artist=song.artist,
                    title=song.title,
                    source=song.source,
                    score=score,
                    year=metadata.year,
                    tags=metadata.tags,
                )
            )
        return dedupe_recommendations(enriched, limit=len(enriched))

    def lookup(self, artist: str, title: str) -> MusicMetadata:
        key = (normalize_song_text(artist), normalize_title_key(title, artist))
        if key in self.cache:
            return self.cache[key]
        self._rate_limit()
        query = f'recording:"{title}" AND artist:"{artist}"'
        try:
            data = self.fetcher(
                self.API_URL,
                {"query": query, "fmt": "json", "limit": 3},
            )
        except Exception as exc:
            if self.verbose:
                print(f"MusicBrainz lookup failed artist={artist!r} title={title!r}: {exc}", file=sys.stderr)
            metadata = MusicMetadata()
        else:
            metadata = parse_musicbrainz_recording_metadata(data)
        self.cache[key] = metadata
        return metadata

    def _rate_limit(self) -> None:
        if self.pause_seconds <= 0:
            return
        elapsed = time.monotonic() - self.last_request_at
        if elapsed < self.pause_seconds:
            time.sleep(self.pause_seconds - elapsed)
        self.last_request_at = time.monotonic()


def parse_musicbrainz_recording_metadata(data: dict[str, Any]) -> MusicMetadata:
    recordings = data.get("recordings", [])
    if not isinstance(recordings, list) or not recordings:
        return MusicMetadata()
    best = recordings[0]
    if not isinstance(best, dict):
        return MusicMetadata()
    year = parse_year(best.get("first-release-date"))
    if year is None:
        for release in best.get("releases", []) if isinstance(best.get("releases"), list) else []:
            if isinstance(release, dict):
                year = parse_year(release.get("date"))
                if year is not None:
                    break
    tags = tuple(
        tag.get("name", "").strip().lower()
        for tag in best.get("tags", [])
        if isinstance(tag, dict) and isinstance(tag.get("name"), str) and tag.get("name", "").strip()
    )
    return MusicMetadata(year=year, tags=tags)


def parse_year(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d{4})", value)
    if not match:
        return None
    year = int(match.group(1))
    return year if 1800 <= year <= 2100 else None


def parse_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_recommendation_providers(*, verbose: bool) -> list[RecommendationProvider]:
    enabled = {
        item.strip().lower()
        for item in os.environ.get("YOUTUBE_CLI_RECOMMENDER", "lastfm,youtube").split(",")
        if item.strip()
    }
    providers: list[RecommendationProvider] = []
    api_key = os.environ.get("LASTFM_API_KEY", "").strip()
    if "lastfm" in enabled and api_key:
        providers.append(LastFmRecommendationProvider(api_key, verbose=verbose))
    elif verbose and "lastfm" in enabled:
        print("Last.fm recommender disabled: LASTFM_API_KEY is not set.", file=sys.stderr)
    return providers


def build_metadata_enricher(*, verbose: bool) -> MusicBrainzEnricher | None:
    enabled = {
        item.strip().lower()
        for item in os.environ.get("YOUTUBE_CLI_RECOMMENDER", "lastfm,youtube").split(",")
        if item.strip()
    }
    if "musicbrainz" not in enabled:
        return None
    return MusicBrainzEnricher(verbose=verbose)
