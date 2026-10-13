from pathlib import Path

import cv2
import numpy as np
import pytest

from eterspire_notifier.detector import PopupDetector, find_panels, load_templates

DOCS = Path(__file__).resolve().parent.parent / "docs"
POPUPS = {
    "popup_inventory_full_fish.png": ("inventory_full", "inventory_full_fish"),
    "popup_inventory_full_logs.png": ("inventory_full", "inventory_full_logs"),
    "popup_spot_empty.png": ("spot_empty", "spot_empty"),
}


@pytest.fixture(scope="module")
def detector():
    return PopupDetector(load_templates())


def game_frame(seed=0):
    """A busy, blurry 1080p background with a decoy panel of the pop-up colour."""
    rng = np.random.default_rng(seed)
    frame = cv2.GaussianBlur(rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8), (31, 31), 0)
    frame[700:900, 1200:1600] = (46, 64, 135)
    return frame


def paste(frame, popup_file, scale, at=(300, 200)):
    popup = cv2.imread(str(DOCS / popup_file))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    popup = cv2.resize(popup, None, fx=scale, fy=scale, interpolation=interp)
    x, y = at
    frame[y : y + popup.shape[0], x : x + popup.shape[1]] = popup
    return frame


@pytest.mark.parametrize("popup_file", POPUPS)
@pytest.mark.parametrize("scale", [0.5, 0.75, 1.0, 1.33, 2.0])
def test_detects_each_popup_at_any_size(detector, popup_file, scale):
    event, template = POPUPS[popup_file]
    found = detector.detect(paste(game_frame(), popup_file, scale))
    assert list(found) == [event]
    assert found[event].template == template
    assert found[event].scale == pytest.approx(scale, rel=0.03)


def test_nothing_found_without_popup(detector):
    assert detector.detect(game_frame()) == {}


def test_decoy_panel_is_a_candidate_but_not_a_match(detector):
    frame = game_frame()
    assert find_panels(frame)
    assert all(m.score < 0.6 for m in detector.scan(frame).values())


def test_repeated_scans_reuse_result(detector):
    frame = paste(game_frame(), "popup_spot_empty.png", 1.2)
    first = detector.detect(frame)
    second = detector.detect(frame)
    assert first.keys() == second.keys() == {"spot_empty"}
