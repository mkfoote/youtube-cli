from __future__ import annotations

import difflib
import re

VERSION_WORDS = {
    "audio",
    "clean",
    "clip",
    "edit",
    "extended",
    "hd",
    "hq",
    "live",
    "lyrics",
    "lyric",
    "mix",
    "music",
    "official",
    "remaster",
    "remastered",
    "remix",
    "session",
    "video",
    "visualizer",
}


def normalize_song_text(value: str) -> str:
    text = value.lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)
    text = re.sub(r"\b\d{4}\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = [word for word in text.split() if word not in VERSION_WORDS]
    return " ".join(words)


def normalize_title_key(title: str, artist: str | None) -> str:
    title_key = normalize_song_text(title)
    artist_key = normalize_song_text(artist or "")
    if artist_key and title_key.startswith(f"{artist_key} "):
        title_key = title_key[len(artist_key) + 1 :]
    return title_key


def song_keys_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) >= 8 and shorter in longer:
        return True
    return difflib.SequenceMatcher(None, left, right).ratio() >= 0.88


def title_key_is_distinctive(value: str) -> bool:
    words = value.split()
    return len(value) >= 8 or len(words) >= 2


def infer_artist_from_title(title: str) -> tuple[str | None, str]:
    cleaned = re.sub(r"\s+", " ", title).strip()
    patterns = [
        r"^(?P<artist>[^-–—:|]{2,80})\s*[-–—:|]\s*(?P<title>[^-–—:|]{2,120})$",
        r"^(?P<artist>[^\"“”]{2,80})\s+[\"“](?P<title>[^\"“”]{2,120})[\"”]$",
    ]
    for pattern in patterns:
        match = re.match(pattern, cleaned)
        if not match:
            continue
        artist = strip_metadata_noise(match.group("artist"))
        song_title = strip_metadata_noise(match.group("title"))
        if artist and song_title and not looks_like_channel_label(artist):
            return artist, song_title
    return None, title


def strip_metadata_noise(value: str) -> str:
    value = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", value)
    return re.sub(r"\s+", " ", value).strip(" -:|")


def looks_like_channel_label(value: str) -> bool:
    text = normalize_song_text(value)
    if not text:
        return True
    return text.endswith("vevo") or text.endswith("records")
