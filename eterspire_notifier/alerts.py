"""Alert outputs: sounds and phone notifications."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np

from .config import PhoneSettings

SOUNDS_DIR = Path(__file__).parent / "sounds"
USER_AGENT = "EterspireNotifier/1.0"

# ---------------------------------------------------------------- sound


def builtin_sound(event: str) -> Path:
    return SOUNDS_DIR / f"{event}.wav"


def _with_volume(path: Path, volume: int) -> bytes:
    """Return the WAV file's bytes with its samples scaled to ``volume`` (0-100)."""
    raw = path.read_bytes()
    try:
        with wave.open(io.BytesIO(raw)) as src:
            params = src.getparams()
            frames = src.readframes(params.nframes)
    except (wave.Error, EOFError):
        return raw
    if params.sampwidth != 2 or volume >= 100:
        return raw  # only 16-bit PCM is rescaled; anything else plays at its own volume
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) * (max(volume, 0) / 100)
    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setparams(params)
        dst.writeframes(samples.astype("<i2").tobytes())
    return out.getvalue()


def _play_blocking(data: bytes) -> None:
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        return
    player = shutil.which("afplay") or shutil.which("paplay") or shutil.which("aplay")
    if not player:
        print("\a", end="", flush=True)
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(data)
    try:
        subprocess.run([player, tmp.name], check=False, capture_output=True)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def play_sound(path: Path, volume: int, on_error=None) -> None:
    """Play a WAV file in the background."""

    def run():
        try:
            _play_blocking(_with_volume(path, volume))
        except Exception as exc:  # noqa: BLE001 - a broken sound must never stop monitoring
            if on_error:
                on_error(f"Could not play {path.name}: {exc}")

    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- phone


class PhoneError(Exception):
    pass


def _post(url: str, data: bytes, headers: dict) -> bytes:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **headers}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise PhoneError(f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PhoneError(f"network error: {getattr(exc, 'reason', exc)}") from exc


def ntfy_url(phone: PhoneSettings) -> str:
    return phone.ntfy_server.strip().rstrip("/") + "/" + urllib.parse.quote(phone.ntfy_topic.strip())


def send_phone(phone: PhoneSettings, title: str, message: str, tags: str = "", urgent: bool = False) -> None:
    """Send a notification with the configured service. Raises PhoneError on failure."""
    service = phone.service
    if service == "ntfy":
        if not phone.ntfy_topic.strip():
            raise PhoneError("no ntfy topic set")
        headers = {"Title": title, "Priority": "high" if urgent else "default"}
        if tags:
            headers["Tags"] = tags
        _post(ntfy_url(phone), message.encode("utf-8"), headers)
    elif service == "discord":
        if not phone.discord_webhook.strip().startswith("https://"):
            raise PhoneError("paste your Discord webhook URL first")
        body = {"username": "Eterspire Notifier", "content": f"**{title}**\n{message}"}
        _post(phone.discord_webhook.strip(), json.dumps(body).encode(), {"Content-Type": "application/json"})
    elif service == "telegram":
        if not phone.telegram_token.strip() or not phone.telegram_chat_id.strip():
            raise PhoneError("enter your Telegram bot token and chat ID first")
        url = f"https://api.telegram.org/bot{phone.telegram_token.strip()}/sendMessage"
        body = {"chat_id": phone.telegram_chat_id.strip(), "text": f"{title}\n{message}"}
        _post(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    else:
        raise PhoneError(f"unknown service {service!r}")


def telegram_find_chat_id(token: str) -> str:
    """Return the chat ID of the latest message sent to the bot. Raises PhoneError."""
    url = f"https://api.telegram.org/bot{token.strip()}/getUpdates"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise PhoneError("Telegram rejected the bot token" if exc.code in (401, 404) else f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise PhoneError(f"network error: {getattr(exc, 'reason', exc)}") from exc
    for update in reversed(data.get("result", [])):
        message = update.get("message") or update.get("channel_post") or {}
        if "chat" in message:
            return str(message["chat"]["id"])
    raise PhoneError("no messages yet: open your bot in Telegram, send it any message, then try again")


def send_phone_async(phone: PhoneSettings, title: str, message: str, tags: str = "", urgent: bool = False, on_done=None):
    """Send in the background; ``on_done(error_or_None)`` is called from the worker thread."""

    def run():
        try:
            send_phone(phone, title, message, tags, urgent)
            error = None
        except PhoneError as exc:
            error = str(exc)
        if on_done:
            on_done(error)

    threading.Thread(target=run, daemon=True).start()
