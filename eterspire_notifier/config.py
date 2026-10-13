"""User settings, persisted as JSON in the user's app-data folder."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path

APP_NAME = "EterspireNotifier"


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_templates_dir() -> Path:
    path = config_dir() / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_ntfy_topic() -> str:
    # Long and random: anyone who knows an ntfy topic name can read it.
    return "eterspire-" + secrets.token_urlsafe(9).replace("_", "x").replace("-", "z").lower()


@dataclass
class EventSettings:
    sound: bool = True
    popup: bool = True
    custom_sound: str = ""  # path to a .wav file, empty = built-in sound
    phone: bool = False
    # Only notify the phone if the in-game pop-up is still open after this many seconds (0 = immediately).
    phone_delay: int = 0


@dataclass
class PhoneSettings:
    service: str = "ntfy"  # ntfy | discord | telegram
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = field(default_factory=new_ntfy_topic)
    discord_webhook: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""


@dataclass
class Settings:
    inventory_full: EventSettings = field(default_factory=EventSettings)
    spot_empty: EventSettings = field(default_factory=lambda: EventSettings(phone_delay=60))
    phone: PhoneSettings = field(default_factory=PhoneSettings)

    volume: int = 80  # 0-100
    repeat_sound_every: int = 0  # seconds between repeats while the pop-up stays open, 0 = play once
    popup_seconds: int = 8  # how long the desktop notification stays on screen

    capture_window: bool = True  # watch only the game window (falls back to the whole screen)
    window_title: str = "Eterspire"
    scan_interval: float = 1.0
    match_threshold: float = 0.70  # how closely the pop-up text must match the reference (0-1)

    autostart: bool = True  # start watching as soon as the app opens

    def event(self, name: str) -> EventSettings:
        return getattr(self, name)


def _merge(obj, data: dict) -> None:
    """Copy known keys from ``data`` into the dataclass ``obj``, ignoring anything malformed."""
    for f in fields(obj):
        if f.name not in data:
            continue
        current, value = getattr(obj, f.name), data[f.name]
        if is_dataclass(current):
            if isinstance(value, dict):
                _merge(current, value)
        elif isinstance(current, bool):
            if isinstance(value, bool):
                setattr(obj, f.name, value)
        elif isinstance(current, (int, float)):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                setattr(obj, f.name, type(current)(value))
        elif isinstance(value, type(current)):
            setattr(obj, f.name, value)


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> Settings:
    settings = Settings()
    try:
        _merge(settings, json.loads(config_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return settings


def save(settings: Settings) -> None:
    path = config_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    os.replace(tmp, path)
