from __future__ import annotations

import argparse
import curses
import signal
import subprocess
import time

from .models import MixCandidate, PlaybackResult, RecommendedSong, Track
from .playback import pause_process, resume_process, stop_process
from .prefetch import MixPrefetcher
from .queue_state import PlaylistState
from .recommendations import (
    LastFmRecommendationProvider,
    MusicBrainzEnricher,
    parse_musicbrainz_recording_metadata,
)
from .search import SearchController
from .view import TerminalUI
from .youtube import YoutubeMixClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Play a requested song, then keep streaming a YouTube-style mix."
    )
    parser.add_argument("song", nargs="*", help="song title, artist, or search query")
    parser.add_argument("--player", help="media player command to use, default: ffplay or mpv")
    parser.add_argument(
        "--max-songs",
        type=int,
        default=0,
        help="stop after this many songs; 0 means play indefinitely",
    )
    parser.add_argument("--verbose", action="store_true", help="show yt-dlp output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    query = " ".join(args.song).strip() or input("Song: ").strip()
    if not query:
        print("No song entered.", file=sys.stderr)
        return 2

    try:
        client = YoutubeMixClient(player=args.player, verbose=args.verbose)
        current = client.search_first(query)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return run_plain(args, client, current)

    return curses.wrapper(run_tui, args, client, current)


def run_plain(args: argparse.Namespace, client: YoutubeMixClient, current: Track) -> int:
    plays = 0
    last_interrupt = 0.0
    prefetcher = MixPrefetcher(client)
    prefetcher.start()

    try:
        while current and (args.max_songs <= 0 or plays < args.max_songs):
            try:
                prefetcher.submit_seed(current)
                client.play(current)
                plays += 1
            except KeyboardInterrupt:
                now = time.monotonic()
                if now - last_interrupt < 1.5:
                    print("\nExiting.")
                    return 130
                last_interrupt = now
                print("\nSkipped. Press Ctrl+C again quickly to quit.")
                plays += 1
            except Exception as exc:
                print(f"\nError: {exc}", file=sys.stderr)

            if args.max_songs <= 0 or plays < args.max_songs:
                current = prefetcher.next_track()
    finally:
        prefetcher.stop()

    return 0


def run_tui(
    screen: curses.window,
    args: argparse.Namespace,
    client: YoutubeMixClient,
    current: Track,
) -> int:
    ui = TerminalUI(screen)
    plays = 0
    status = "buffering mix"
    prefetcher = MixPrefetcher(client)
    prefetcher.start()
    search = SearchController(client, prefetcher)

    try:
        while current and (args.max_songs <= 0 or plays < args.max_songs):
            prefetcher.submit_seed(current)
            result = play_with_ui(
                client=client,
                prefetcher=prefetcher,
                search=search,
                ui=ui,
                current=current,
                plays=plays,
                status=status,
            )

            if result.action == "quit":
                return 0

            plays += 1
            status = result.action

            if args.max_songs > 0 and plays >= args.max_songs:
                break

            current = result.track or wait_for_next_track(ui, prefetcher, search, current, plays, status)
            if current is None:
                return 0
    finally:
        prefetcher.stop()

    return 0


def play_with_ui(
    *,
    client: YoutubeMixClient,
    prefetcher: MixPrefetcher,
    search: SearchController,
    ui: TerminalUI,
    current: Track,
    plays: int,
    status: str,
) -> PlaybackResult:
    process = client.start_player(current)
    started_at = time.monotonic()
    local_status = status
    paused = False
    pause_started_at = 0.0
    paused_seconds = 0.0

    try:
        while process.poll() is None:
            now = time.monotonic()
            elapsed = pause_started_at - started_at - paused_seconds if paused else now - started_at - paused_seconds
            ui.draw(
                current=current,
                queue_tracks=prefetcher.snapshot(),
                elapsed=elapsed,
                status=local_status,
                plays=plays,
                search_state=search.snapshot(),
            )

            raw_key = ui.read_raw_key()
            search_state = search.snapshot()
            if search_state["mode"] != "queue":
                search_status = search.handle_key(raw_key)
                local_status = search_status or local_status
                time.sleep(0.2)
                continue

            action = ui.translate_key(raw_key)
            if action in {"quit", "skip"}:
                stop_process(process)
                return PlaybackResult(action)
            if action == "search":
                local_status = search.open()
            if action == "pause":
                if paused:
                    resume_process(process)
                    paused_seconds += time.monotonic() - pause_started_at
                    paused = False
                    local_status = "playing"
                else:
                    pause_process(process)
                    pause_started_at = time.monotonic()
                    paused = True
                    local_status = "paused"
            if action in {"up", "down", "delete", "jump"}:
                queue_action = handle_queue_action(action, ui, prefetcher)
                if isinstance(queue_action, Track):
                    stop_process(process)
                    return PlaybackResult("jumped", queue_action)
                local_status = queue_action or local_status

            time.sleep(0.2)
    except KeyboardInterrupt:
        stop_process(process)
        return PlaybackResult("quit")

    return PlaybackResult("finished")


def wait_for_next_track(
    ui: TerminalUI,
    prefetcher: MixPrefetcher,
    search: SearchController,
    previous: Track,
    plays: int,
    status: str,
) -> Track | None:
    started_waiting = time.monotonic()
    local_status = status
    while True:
        track = prefetcher.next_track_nowait()
        if track:
            return track

        elapsed = min(previous.duration or 0, previous.duration or 0)
        wait_seconds = int(time.monotonic() - started_waiting)
        ui.draw(
            current=previous,
            queue_tracks=prefetcher.snapshot(),
            elapsed=elapsed,
            status=f"{local_status}; waiting for next track ({wait_seconds}s)",
            plays=plays,
            search_state=search.snapshot(),
        )

        raw_key = ui.read_raw_key()
        search_state = search.snapshot()
        if search_state["mode"] != "queue":
            search_status = search.handle_key(raw_key)
            local_status = search_status or local_status
            time.sleep(0.2)
            continue

        action = ui.translate_key(raw_key)
        if action == "quit":
            return None
        if action == "search":
            local_status = search.open()
        if action in {"up", "down", "delete", "jump"}:
            queue_action = handle_queue_action(action, ui, prefetcher)
            if isinstance(queue_action, Track):
                return queue_action
            local_status = queue_action or local_status
        time.sleep(0.2)


def handle_queue_action(
    action: str,
    ui: TerminalUI,
    prefetcher: MixPrefetcher,
) -> str | Track | None:
    queue_length = len(prefetcher.snapshot())
    if action == "up":
        ui.move_selection(-1, queue_length)
        return None
    if action == "down":
        ui.move_selection(1, queue_length)
        return None
    if action == "delete":
        index = ui.selected_queue_index(queue_length)
        if index is None:
            return "queue empty"
        removed = prefetcher.remove(index)
        ui.move_selection(0, len(prefetcher.snapshot()))
        if removed:
            return f"removed {removed.label}"
    if action == "jump":
        index = ui.selected_queue_index(queue_length)
        if index is None:
            return "queue empty"
        selected = prefetcher.remove(index)
        ui.move_selection(0, len(prefetcher.snapshot()))
        if selected:
            return selected
    return None


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    raise SystemExit(main())
