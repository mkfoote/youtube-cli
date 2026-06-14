# youtube-cli

A terminal-only YouTube music client. It prompts for a song, uses `yt-dlp` to
resolve a playable audio stream, plays it with a CLI media player, then keeps
prefetching related tracks in the background in a YouTube mix style.

## Requirements

- Python 3.10+
- `yt-dlp` Python package
- A command-line media player:
  - `ffplay` from FFmpeg, or
  - `mpv`

## Install

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Run

```sh
youtube-cli
```

Or pass the first song directly:

```sh
youtube-cli "massive attack teardrop"
```

Useful options:

```sh
youtube-cli --player mpv "radiohead reckoner"
youtube-cli --max-songs 25 "erykah badu on and on"
youtube-cli --verbose "daft punk something about us"
```

For genre-aware queue recommendations, set a Last.fm API key:

```sh
export LASTFM_API_KEY="..."
youtube-cli "radiohead reckoner"
```

With `LASTFM_API_KEY` set, the queue asks Last.fm for similar tracks and top
tracks from similar artists, then resolves those songs through YouTube for
playback. If Last.fm is unavailable or returns nothing playable, the app falls
back to the built-in YouTube related/search queue.

Optional MusicBrainz era/tag enrichment can be enabled with:

```sh
export YOUTUBE_CLI_RECOMMENDER="lastfm,musicbrainz,youtube"
```

MusicBrainz enrichment reorders the front of the Last.fm candidate list toward
recordings with nearby release years and overlapping tags. It is off by default
because MusicBrainz is rate-limited and can slow background queue fills.

Playback starts as soon as the first song is resolved. The mix queue is filled
in the background while the current song is playing. By default playback
continues indefinitely until you stop it.
When using `ffplay`, media is streamed through `yt-dlp` instead of handing
`ffplay` a temporary YouTube media URL directly, which makes playback less
likely to stop early on transient stream issues.

The default interactive view is a terminal UI with the upcoming queue and a
bottom now-playing progress bar. If stdout or stdin is not attached to a
terminal, the app falls back to plain text output.

Before tracks are added to the queue, the app normalizes title and artist
metadata for duplicate detection. Recommended songs are resolved through
YouTube and added unless they are already known duplicates or the queue buffer
is full.

While a song is playing:

- Let it finish to continue the mix.
- Press `/` to search for another song.
- Type a search term and press `enter` to show results.
- Use up/down arrows in search results and press `enter` to add the highlighted result to the queue.
- Press `esc` to close search and return to queue control.
- Press the up/down arrows to select an item in the queue.
- Press `enter` to jump immediately to the selected queue item.
- Press `delete` or `backspace` to remove the selected queue item.
- Press `space` to pause or resume playback.
- Press `s` to skip the current song.
- Press `q` to quit.
