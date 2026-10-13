"""Background thread that watches the screen and reports pop-up events."""

from __future__ import annotations

import threading
import time
from typing import Callable

from . import config
from .capture import ScreenGrabber, Target, find_window
from .config import Settings
from .detector import EVENTS, Match, PopupDetector, load_templates
from .tracker import PopupTracker

# emit(kind, payload) is called from the monitor thread:
#   ("status", str)                                - what is being watched
#   ("action", (event, action, Match | None))      - see tracker.py for actions
#   ("error", str)
Emit = Callable[[str, object], None]


def capture_target(settings: Settings, grabber: ScreenGrabber) -> tuple[Target, str]:
    """Return what to capture and a status text describing it."""
    if settings.capture_window:
        target, status = find_window(settings.window_title)
        if target:
            return target, f"Watching the {status}"
        return grabber.all_screens(), f"Watching all screens: {status}"
    return grabber.all_screens(), "Watching all screens"


def scan_once(settings: Settings) -> tuple[str, dict[str, Match]]:
    """Take one screenshot and return every template's best score (for the "Test detection" button)."""
    grabber = ScreenGrabber()
    try:
        target, status = capture_target(settings, grabber)
        detector = PopupDetector(load_templates(config.user_templates_dir()), settings.match_threshold)
        return status, detector.scan(grabber.grab(target))
    finally:
        grabber.close()


class Monitor(threading.Thread):
    def __init__(self, settings: Settings, emit: Emit):
        super().__init__(name="monitor", daemon=True)
        self.settings = settings
        self.emit = emit
        self._stop = threading.Event()
        self._reload = threading.Event()
        self.trackers = {event: PopupTracker() for event in EVENTS}

    def stop(self) -> None:
        self._stop.set()

    def reload_templates(self) -> None:
        self._reload.set()

    def run(self) -> None:
        grabber = ScreenGrabber()
        detector = PopupDetector(load_templates(config.user_templates_dir()), self.settings.match_threshold)
        last_status = None
        last_match: dict[str, Match] = {}
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                if self._reload.is_set():
                    self._reload.clear()
                    detector = PopupDetector(load_templates(config.user_templates_dir()), self.settings.match_threshold)
                detector.threshold = self.settings.match_threshold

                target, status = capture_target(self.settings, grabber)
                if status != last_status:
                    self.emit("status", status)
                    last_status = status
                try:
                    shot = grabber.grab(target)
                except Exception as exc:  # noqa: BLE001 - e.g. a monitor got unplugged; try again next tick
                    self.emit("error", f"Screen capture failed: {exc}")
                    self._stop.wait(5)
                    continue

                found = detector.detect(shot)
                now = time.monotonic()
                for event, tracker in self.trackers.items():
                    if event in found:
                        last_match[event] = found[event]
                    actions = tracker.update(
                        event in found, now, self.settings.event(event), self.settings.repeat_sound_every
                    )
                    for action in actions:
                        self.emit("action", (event, action, last_match.get(event)))

                elapsed = time.monotonic() - started
                self._stop.wait(max(0.2, self.settings.scan_interval - elapsed))
        finally:
            grabber.close()
