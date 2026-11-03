from __future__ import annotations

import configparser
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

APP_NAME = "youtube-cli"
CONFIG_FILE_ENV = "YOUTUBE_CLI_CONFIG_FILE"
LASTFM_API_KEY_ENV = "LASTFM_API_KEY"


def config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    explicit_path = env.get(CONFIG_FILE_ENV, "").strip()
    if explicit_path:
        return Path(explicit_path).expanduser()

    config_home = env.get("XDG_CONFIG_HOME", "").strip()
    base_dir = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return base_dir / APP_NAME / "config.ini"


def load_config(path: Path | None = None) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(path or config_path())
    return parser


def lastfm_api_key(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    environment_key = env.get(LASTFM_API_KEY_ENV, "").strip()
    if environment_key:
        return environment_key

    path = config_path(env)
    return load_config(path).get("lastfm", "api_key", fallback="").strip()


def lastfm_api_key_source(environ: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if environ is None else environ
    if env.get(LASTFM_API_KEY_ENV, "").strip():
        return "environment"
    if lastfm_api_key(env):
        return "config file"
    return None


def save_lastfm_api_key(api_key: str, path: Path | None = None) -> Path:
    value = api_key.strip()
    if not value:
        raise ValueError("Last.fm API key cannot be empty")

    destination = path or config_path()
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parser = load_config(destination)
    if not parser.has_section("lastfm"):
        parser.add_section("lastfm")
    parser.set("lastfm", "api_key", value)
    _write_config(parser, destination)
    return destination


def clear_lastfm_api_key(path: Path | None = None) -> bool:
    destination = path or config_path()
    parser = load_config(destination)
    if not parser.has_section("lastfm"):
        return False
    removed = parser.remove_option("lastfm", "api_key")
    if not removed:
        return False
    if parser.has_section("lastfm") and not parser.items("lastfm"):
        parser.remove_section("lastfm")
    _write_config(parser, destination)
    return True


def _write_config(parser: configparser.ConfigParser, destination: Path) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            os.chmod(temporary_path, 0o600)
            parser.write(handle)
        temporary_path.replace(destination)
        os.chmod(destination, 0o600)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
