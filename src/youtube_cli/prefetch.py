from __future__ import annotations

import queue
import sys
import threading
import time
from typing import Iterable

from .models import MixCandidate, RecommendationProvider, RecommendedSong, Track
from .queue_state import PlaylistState
from .recommendations import (
    METADATA_ENRICH_LIMIT,
    MusicBrainzEnricher,
    build_metadata_enricher,
    build_recommendation_providers,
    dedupe_recommendations,
)
from .youtube import YoutubeMixClient

MIX_RESOLVE_BATCH_SIZE = 8
MAX_MIX_CANDIDATES_PER_SEED = 48


class MixPrefetcher:
    def __init__(
        self,
        client: YoutubeMixClient,
        *,
        buffer_size: int = 6,
        retry_delay: float = 3.0,
        recommendation_providers: list[RecommendationProvider] | None = None,
        metadata_enricher: MusicBrainzEnricher | None = None,
    ) -> None:
        self.client = client
        self.playlist = PlaylistState(max_size=buffer_size)
        self.seeds: queue.Queue[Track] = queue.Queue()
        self.stop_event = threading.Event()
        self.retry_delay = retry_delay
        self.thread = threading.Thread(target=self._run, name="mix-prefetch", daemon=True)
        self.submitted_seeds: set[str] = set()
        self.queued_urls: set[str] = set()
        self.lock = threading.Lock()
        self.last_seed: Track | None = None
        self.recommendation_providers = (
            recommendation_providers
            if recommendation_providers is not None
            else build_recommendation_providers(verbose=client.verbose)
        )
        self.metadata_enricher = (
            metadata_enricher
            if metadata_enricher is not None
            else build_metadata_enricher(verbose=client.verbose)
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def submit_seed(self, track: Track) -> None:
        self.playlist.remember(track)
        with self.lock:
            if track.webpage_url in self.submitted_seeds:
                return
            self.submitted_seeds.add(track.webpage_url)
        self.seeds.put(track)

    def next_track(self) -> Track:
        return self.playlist.pop_next(stop_event=self.stop_event)

    def next_track_nowait(self) -> Track | None:
        return self.playlist.pop_next_nowait()

    def snapshot(self) -> list[Track]:
        return self.playlist.snapshot()

    def remove(self, index: int) -> Track | None:
        return self.playlist.remove(index)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            seed = self._next_seed()
            if seed is None:
                time.sleep(self.retry_delay)
                continue

            self.last_seed = seed
            produced = self._prefetch_from_seed(seed)
            if not produced and not self.stop_event.is_set():
                time.sleep(self.retry_delay)
                self.seeds.put(seed)

    def _next_seed(self) -> Track | None:
        try:
            return self.seeds.get(timeout=1)
        except queue.Empty:
            if self.last_seed and self.playlist.qsize() < 2:
                return self.last_seed
            return None

    def _prefetch_from_seed(self, seed: Track) -> int:
        produced = 0
        try:
            produced += self._prefetch_recommendations(seed)
            if produced or self.playlist.qsize() >= self.playlist.max_size:
                return produced
            for candidate_refs in self._candidate_batches(self.client.mix_candidates(seed)):
                candidates = self._resolve_candidates(candidate_refs)
                produced += self._add_candidates(candidates)
                if self.playlist.qsize() >= self.playlist.max_size:
                    break
        except Exception as exc:
            if self.client.verbose:
                print(f"Could not extend mix: {exc}", file=sys.stderr)
        return produced

    def _prefetch_recommendations(self, seed: Track) -> int:
        if not self.recommendation_providers:
            return 0
        produced = 0
        songs = self._recommend_songs(seed)
        if self.metadata_enricher and songs:
            enriched = self.metadata_enricher.enrich(seed, songs[:METADATA_ENRICH_LIMIT])
            songs = dedupe_recommendations([*enriched, *songs[METADATA_ENRICH_LIMIT:]], limit=len(songs))
        for song in songs:
            if self.stop_event.is_set() or self.playlist.qsize() >= self.playlist.max_size:
                break
            track = self._resolve_recommended_song(song)
            if not track:
                continue
            if self.playlist.add(track, stop_event=self.stop_event):
                produced += 1
            elif self.client.verbose:
                print(f"recommended skipped title={track.label!r}", file=sys.stderr)
        return produced

    def _recommend_songs(self, seed: Track) -> list[RecommendedSong]:
        songs: list[RecommendedSong] = []
        for provider in self.recommendation_providers:
            try:
                provider_songs = provider.recommendations(seed, limit=MAX_MIX_CANDIDATES_PER_SEED)
            except Exception as exc:
                if self.client.verbose:
                    print(f"Recommendation provider failed: {exc}", file=sys.stderr)
                continue
            if self.client.verbose:
                print(
                    f"recommendation provider={provider.__class__.__name__} "
                    f"count={len(provider_songs)}",
                    file=sys.stderr,
                )
            songs.extend(provider_songs)
        return dedupe_recommendations(songs, limit=MAX_MIX_CANDIDATES_PER_SEED)

    def _resolve_recommended_song(self, song: RecommendedSong) -> Track | None:
        if self.client.verbose:
            year = f" year={song.year}" if song.year else ""
            print(
                f"recommended score={song.score:.1f}{year} "
                f"source={song.source} title={song.label!r}",
                file=sys.stderr,
            )
        track = self.client.resolve_recommended_song(song)
        if track and self._claim_url(track.webpage_url, allow_client_seen=True):
            return track
        return None

    def _candidate_batches(self, candidates: Iterable[MixCandidate]) -> Iterable[list[MixCandidate]]:
        batch: list[MixCandidate] = []
        seen = 0
        for candidate in candidates:
            if self.stop_event.is_set():
                break
            batch.append(candidate)
            seen += 1
            if len(batch) >= MIX_RESOLVE_BATCH_SIZE:
                yield batch
                batch = []
            if seen >= MAX_MIX_CANDIDATES_PER_SEED:
                break
        if batch:
            yield batch

    def _resolve_candidates(self, candidates: list[MixCandidate]) -> list[Track]:
        resolved: list[Track] = []
        for candidate in candidates:
            if self.stop_event.is_set():
                break
            if not self._claim_url(candidate.url):
                continue

            try:
                track = self.client.resolve(candidate.url)
            except Exception as exc:
                if self.client.verbose:
                    print(f"Skipping unavailable result: {exc}", file=sys.stderr)
                continue

            if self.client.verbose:
                print(
                    "candidate "
                    f"rank={candidate.source_rank + 1} title={track.label!r}",
                    file=sys.stderr,
                )
            resolved.append(track)
        return resolved

    def _add_candidates(self, candidates: list[Track]) -> int:
        produced = 0
        for track in candidates:
            if self.stop_event.is_set():
                break
            if self.playlist.qsize() >= self.playlist.max_size:
                break
            if self.playlist.add(track, stop_event=self.stop_event):
                produced += 1
            elif self.client.verbose:
                print(f"candidate skipped title={track.label!r}", file=sys.stderr)
        return produced

    def _claim_url(self, url: str, *, allow_client_seen: bool = False) -> bool:
        with self.lock:
            if (not allow_client_seen and url in self.client.seen) or url in self.queued_urls:
                return False
            self.queued_urls.add(url)
            return True
