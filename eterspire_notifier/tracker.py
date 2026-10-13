"""Turns "is the pop-up on screen right now?" samples into alert actions."""

from __future__ import annotations

from .config import EventSettings

ALERT = "alert"  # pop-up just appeared: play sound / show desktop notification
REPEAT_SOUND = "repeat_sound"  # pop-up still open, time to play the sound again
PHONE = "phone"  # notify the phone now
CLOSED = "closed"  # the player closed the pop-up


class PopupTracker:
    """State of one kind of pop-up across scans.

    A pop-up only counts as closed after it was missing from ``close_after_misses``
    scans in a row, so one bad frame doesn't trigger a second alert.
    """

    def __init__(self, close_after_misses: int = 2):
        self.close_after_misses = close_after_misses
        self.open = False
        self.opened_at = 0.0
        self.last_sound = 0.0
        self.phone_sent = False
        self.misses = 0

    def update(self, seen: bool, now: float, cfg: EventSettings, repeat_every: float = 0) -> list[str]:
        actions = []
        if seen:
            self.misses = 0
            if not self.open:
                self.open = True
                self.opened_at = self.last_sound = now
                self.phone_sent = False
                actions.append(ALERT)
            elif cfg.sound and repeat_every > 0 and now - self.last_sound >= repeat_every:
                self.last_sound = now
                actions.append(REPEAT_SOUND)
            if cfg.phone and not self.phone_sent and now - self.opened_at >= max(cfg.phone_delay, 0):
                self.phone_sent = True
                actions.append(PHONE)
        elif self.open:
            self.misses += 1
            if self.misses >= self.close_after_misses:
                self.open = False
                actions.append(CLOSED)
        return actions
