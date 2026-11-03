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

## Install for everyday use

Run the installer from this repository:

```sh
./install.sh
```

This creates an isolated environment under `~/.local/share/youtube-cli` and a
`youtube-cli` command under `~/.local/bin`. You do not need to activate a
virtual environment. If the installer says `~/.local/bin` is not on `PATH`, add
the line it prints to your shell profile and open a new terminal.

Run the same command again whenever you want to update the installed copy from
this checkout.

You can customize the locations with `YOUTUBE_CLI_INSTALL_DIR` and
`YOUTUBE_CLI_BIN_DIR`, or select a Python interpreter with `PYTHON`.

Alternatively, if you already use
[`pipx`](https://pipx.pypa.io/stable/), install the package with:

```sh
pipx install .
```

For development, use an editable virtual-environment install:

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
youtube-cli "dreams van halen"
```

Useful options:

```sh
youtube-cli --player mpv  # use specific player
youtube-cli --max-songs 25  # stop playing after the number of songs is reached
```

To get better recommendations in the queue, get a free
[Last.fm API key](https://www.last.fm/api), then save it once:

```sh
youtube-cli config
```

The prompt hides the key while you type it. It is stored in
`~/.config/youtube-cli/config.ini` with user-only permissions. If
`XDG_CONFIG_HOME` is set, that directory is used instead. To inspect the status
without displaying the key, or remove the saved key, run:

```sh
youtube-cli config show
youtube-cli config clear
```

`LASTFM_API_KEY` is still supported and takes precedence over the saved value,
which is useful for temporary overrides. With a key configured, the queue asks
Last.fm for similar tracks and top tracks from similar artists, then resolves
those songs through YouTube for playback. If Last.fm is unavailable or returns
nothing playable, the app falls back to the built-in YouTube related/search
queue.

Optional MusicBrainz era/tag enrichment can be enabled with:

```sh
export YOUTUBE_CLI_RECOMMENDER="lastfm,musicbrainz,youtube"
```

MusicBrainz enrichment reorders the front of the Last.fm candidate list toward
recordings with nearby release years and overlapping tags. It is off by default
because MusicBrainz is rate-limited and can slow background queue fills.

# Experience

Playback starts as soon as the first song is resolved. The mix queue is filled
in the background while the current song is playing. By default playback
continues indefinitely until you stop it.

The default interactive view is a terminal UI with the upcoming queue and a
bottom now-playing progress bar. If stdout or stdin is not attached to a
terminal, the app falls back to plain text output.

Before tracks are added to the queue, the app normalizes title and artist
metadata for duplicate detection. Recommended songs are resolved through
YouTube and added unless they are already known duplicates or the queue buffer
is full.

# Search
Search uses a focused full-screen results view and hides the queue while it is open.
Search rows show `...` while resolving, `+` after adding, `=` for duplicates, and `!` on failure.
If the queue is full, manual adds replace the last queued item.


# Controls

- Vi keys (h/j/k/l) work in the same manner as the corresponding arrow keys
- Press the up/down arrows to select an item in the queue.
- Press `enter` to immediately play the selected queue item.
- Press `delete` or `backspace` to remove the selected queue item.
- Press the left arrow to restart the current song.
- Press `space` to pause or resume playback.
- Press `s` or right arrow to skip the current song.
- Press `q` to quit.
- Press `/` to search for another song.
  - Type a search term and press `enter` to show results.
  - Use up/down arrows in search results.
  - Press `enter` or `a` to add the highlighted result to the end of the queue.
  - Press `n` to add the highlighted result as the next song.
  - Press `j` to resolve and play the highlighted result immediately.
  - Press `esc` to close search and return to queue control.

