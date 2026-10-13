from eterspire_notifier.config import EventSettings
from eterspire_notifier.tracker import ALERT, CLOSED, PHONE, REPEAT_SOUND, PopupTracker


def run(tracker, cfg, samples, repeat_every=0):
    """samples: list of (time, seen); returns {time: actions} for non-empty steps."""
    out = {}
    for now, seen in samples:
        actions = tracker.update(seen, now, cfg, repeat_every)
        if actions:
            out[now] = actions
    return out


def test_alerts_once_per_popup():
    result = run(PopupTracker(), EventSettings(), [(0, True), (1, True), (2, True)])
    assert result == {0: [ALERT]}


def test_phone_right_away_when_no_delay():
    result = run(PopupTracker(), EventSettings(phone=True, phone_delay=0), [(0, True), (1, True)])
    assert result == {0: [ALERT, PHONE]}


def test_phone_only_if_popup_still_open_after_delay():
    cfg = EventSettings(phone=True, phone_delay=30)
    samples = [(t, True) for t in range(0, 31, 5)]
    assert run(PopupTracker(), cfg, samples) == {0: [ALERT], 30: [PHONE]}


def test_no_phone_if_player_closes_popup_in_time():
    cfg = EventSettings(phone=True, phone_delay=30)
    samples = [(0, True), (10, True), (11, False), (12, False), (40, False)]
    assert run(PopupTracker(), cfg, samples) == {0: [ALERT], 12: [CLOSED]}


def test_single_missed_frame_does_not_reset():
    cfg = EventSettings(phone=True, phone_delay=5)
    samples = [(0, True), (1, False), (2, True), (5, True)]
    assert run(PopupTracker(), cfg, samples) == {0: [ALERT], 5: [PHONE]}


def test_new_popup_after_close_alerts_again():
    samples = [(0, True), (1, False), (2, False), (3, True)]
    assert run(PopupTracker(), EventSettings(), samples) == {0: [ALERT], 2: [CLOSED], 3: [ALERT]}


def test_repeat_sound():
    samples = [(t, True) for t in range(0, 25, 5)]
    assert run(PopupTracker(), EventSettings(), samples, repeat_every=10) == {
        0: [ALERT],
        10: [REPEAT_SOUND],
        20: [REPEAT_SOUND],
    }


def test_phone_disabled_never_sends():
    samples = [(t, True) for t in range(0, 100, 10)]
    assert run(PopupTracker(), EventSettings(phone=False), samples) == {0: [ALERT]}
