import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from youtube_cli.app import (
    LastFmRecommendationProvider,
    MusicBrainzEnricher,
    RecommendedSong,
    Track,
    MixPrefetcher,
    parse_musicbrainz_recording_metadata,
)


class RecommendationTests(unittest.TestCase):
    def test_lastfm_provider_merges_similar_tracks_and_similar_artist_tracks(self) -> None:
        def fetcher(_url, params):
            method = params["method"]
            if method == "track.getsimilar":
                return {
                    "similartracks": {
                        "track": [
                            {
                                "name": "Sour Times",
                                "match": "0.92",
                                "artist": {"name": "Portishead"},
                            }
                        ]
                    }
                }
            if method == "artist.getsimilar":
                return {
                    "similarartists": {
                        "artist": [{"name": "Massive Attack", "match": "0.8"}]
                    }
                }
            if method == "artist.gettoptracks":
                return {
                    "toptracks": {
                        "track": [
                            {
                                "name": "Teardrop",
                                "artist": {"name": "Massive Attack"},
                            }
                        ]
                    }
                }
            return {}

        provider = LastFmRecommendationProvider("key", fetcher=fetcher)
        seed = Track("Glory Box", "stream", "https://example.com/seed", artist="Portishead")

        songs = provider.recommendations(seed, limit=10)

        self.assertEqual([song.label for song in songs], ["Portishead - Sour Times", "Massive Attack - Teardrop"])

    def test_musicbrainz_metadata_parser_reads_year_and_tags(self) -> None:
        metadata = parse_musicbrainz_recording_metadata(
            {
                "recordings": [
                    {
                        "first-release-date": "1997-06-16",
                        "tags": [{"name": "alternative rock"}, {"name": "britpop"}],
                    }
                ]
            }
        )

        self.assertEqual(metadata.year, 1997)
        self.assertEqual(metadata.tags, ("alternative rock", "britpop"))

    def test_musicbrainz_enrichment_boosts_same_era_candidates(self) -> None:
        def fetcher(_url, params):
            query = params["query"]
            if "Seed Song" in query:
                return {"recordings": [{"first-release-date": "1974-01-01"}]}
            if "Same Era" in query:
                return {"recordings": [{"first-release-date": "1976-01-01"}]}
            if "Far Away" in query:
                return {"recordings": [{"first-release-date": "2005-01-01"}]}
            return {}

        enricher = MusicBrainzEnricher(fetcher=fetcher, pause_seconds=0)
        seed = Track("Seed Song", "stream", "https://example.com/seed", artist="Seed Artist")
        songs = [
            RecommendedSong("Artist", "Far Away", "test", 50),
            RecommendedSong("Artist", "Same Era", "test", 50),
        ]

        enriched = enricher.enrich(seed, songs)

        self.assertEqual(enriched[0].title, "Same Era")
        self.assertGreater(enriched[0].score, enriched[1].score)

    def test_prefetch_uses_recommendation_provider_before_youtube_fallback(self) -> None:
        class Provider:
            def recommendations(self, seed, *, limit):
                return [RecommendedSong("Artist", "Recommended", "test", 100)]

        class Client:
            verbose = False

            def __init__(self):
                self.seen = set()
                self.fallback_called = False

            def resolve_recommended_song(self, song):
                return Track(song.title, "stream", f"https://example.com/{song.title}", artist=song.artist)

            def mix_candidates(self, seed):
                self.fallback_called = True
                return iter(())

        client = Client()
        prefetcher = MixPrefetcher(client, recommendation_providers=[Provider()])
        seed = Track("Seed", "stream", "https://example.com/seed", artist="Seed Artist")

        produced = prefetcher._prefetch_from_seed(seed)

        self.assertEqual(produced, 1)
        self.assertFalse(client.fallback_called)
        self.assertEqual(prefetcher.snapshot()[0].label, "Artist - Recommended")


if __name__ == "__main__":
    unittest.main()
