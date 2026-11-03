import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from youtube_cli.app import MixCandidate, MixPrefetcher, PlaylistState, Track


class QueueTests(unittest.TestCase):
    def test_playlist_accepts_basic_track(self) -> None:
        playlist = PlaylistState(max_size=2)
        track = Track(
            title="Long Interview Version",
            artist="Example Artist",
            duration=3600,
            url="stream",
            webpage_url="https://example.com/watch?v=one",
        )

        self.assertTrue(playlist.add(track, stop_event=threading.Event()))
        self.assertEqual(playlist.snapshot(), [track])

    def test_playlist_rejects_duplicate_track(self) -> None:
        playlist = PlaylistState(max_size=2)
        stop_event = threading.Event()
        track = Track(
            title="Song",
            artist="Artist",
            duration=200,
            url="stream",
            webpage_url="https://example.com/watch?v=one",
        )

        self.assertTrue(playlist.add(track, stop_event=stop_event))
        self.assertFalse(playlist.add(track, stop_event=stop_event))

    def test_candidate_batches_are_limited(self) -> None:
        prefetcher = MixPrefetcher.__new__(MixPrefetcher)
        prefetcher.stop_event = threading.Event()
        candidates = (
            MixCandidate(f"https://example.com/{index}", "search", index)
            for index in range(100)
        )

        batches = list(prefetcher._candidate_batches(candidates))

        self.assertEqual(sum(len(batch) for batch in batches), 48)
        self.assertTrue(all(len(batch) <= 8 for batch in batches))

    def test_pending_track_is_visible_and_then_resolved(self) -> None:
        playlist = PlaylistState(max_size=3)
        stop_event = threading.Event()

        self.assertTrue(
            playlist.add_pending(
                title="Manual Song",
                artist="Artist",
                webpage_url="https://example.com/manual",
                stop_event=stop_event,
            )
        )
        self.assertEqual(playlist.snapshot()[0].label, "Artist - Resolving: Manual Song")

        resolved = Track("Manual Song", "stream", "https://example.com/manual", artist="Artist")
        self.assertTrue(playlist.resolve_pending("https://example.com/manual", resolved))
        self.assertEqual(playlist.pop_next_nowait(), resolved)

    def test_pending_track_can_be_inserted_next(self) -> None:
        playlist = PlaylistState(max_size=3)
        stop_event = threading.Event()
        later = Track("Later", "stream", "https://example.com/later", artist="Artist")

        self.assertTrue(playlist.add(later, stop_event=stop_event))
        self.assertTrue(
            playlist.add_pending(
                title="Next",
                artist="Other",
                webpage_url="https://example.com/next",
                stop_event=stop_event,
                play_next=True,
            )
        )

        self.assertEqual(playlist.snapshot()[0].label, "Other - Resolving: Next")

    def test_pending_track_overwrites_last_item_when_queue_is_full(self) -> None:
        playlist = PlaylistState(max_size=1)
        stop_event = threading.Event()
        existing = Track("Existing", "stream", "https://example.com/existing")

        self.assertTrue(playlist.add(existing, stop_event=stop_event))
        self.assertTrue(
            playlist.add_pending(
                title="Manual Song",
                artist=None,
                webpage_url="https://example.com/manual",
                stop_event=stop_event,
                wait_for_space=False,
            )
        )
        self.assertEqual(playlist.snapshot()[0].label, "Resolving: Manual Song")


if __name__ == "__main__":
    unittest.main()
