"""Finds the game's pop-ups on a screenshot.

Detection runs in two stages so it works at any game window size and stays cheap
while the game sits AFK:

1. Candidates: every pop-up has the same flat red-brown panel. Pixels of that
   colour are grouped into blobs, and blobs shaped like a pop-up are kept. The
   blob's width tells how big the pop-up is drawn on screen.
2. Verification: the text line of each known pop-up (``templates/*.png``) is
   matched inside each candidate, at sizes close to the one measured in step 1.
   The best match above the threshold says which pop-up is open.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

# template file name -> event it signals
TEMPLATES = {
    "inventory_full_fish": "inventory_full",
    "inventory_full_logs": "inventory_full",
    "spot_empty": "spot_empty",
}
EVENTS = ("inventory_full", "spot_empty")

BUILTIN_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Inner panel width of the pop-ups in the screenshots the templates were cut from.
REFERENCE_PANEL_WIDTH = 414
# Panel colour (HSV, OpenCV ranges). The game draws it as BGR (46, 64, 135).
PANEL_HSV_LOW = (2, 130, 100)
PANEL_HSV_HIGH = (10, 205, 170)


@dataclass
class Match:
    template: str
    event: str
    score: float
    scale: float
    box: tuple[int, int, int, int]  # x, y, w, h in screenshot pixels


def load_gray(path: Path) -> np.ndarray | None:
    # np.fromfile + imdecode instead of imread so non-ASCII Windows paths work.
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)


def load_templates(override_dir: Path | None = None) -> dict[str, np.ndarray]:
    """Load built-in templates; a PNG with the same name in ``override_dir`` replaces one."""
    templates = {}
    for name in TEMPLATES:
        for folder in (override_dir, BUILTIN_TEMPLATES_DIR):
            if folder is None:
                continue
            path = folder / f"{name}.png"
            if path.is_file():
                img = load_gray(path)
                if img is not None:
                    templates[name] = img
                    break
    return templates


def _smooth(gray: np.ndarray) -> np.ndarray:
    # A light blur makes matching tolerant to the small size and anti-aliasing differences
    # between the reference screenshots and the game's own rendering.
    return cv2.GaussianBlur(gray, (3, 3), 0)


def find_panels(bgr: np.ndarray, max_panels: int = 6) -> list[tuple[int, int, int, int]]:
    """Return bounding boxes of pop-up-shaped blobs of the panel colour, largest first."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, PANEL_HSV_LOW, PANEL_HSV_HIGH)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    panels = []
    for x, y, w, h, area in stats[1:count]:
        if w < 120 or h < 30:
            continue
        if not 1.4 <= w / h <= 5.0:
            continue
        if area < 0.45 * w * h:  # text and icons punch holes in the panel, but it's mostly solid
            continue
        panels.append((int(x), int(y), int(w), int(h)))
    panels.sort(key=lambda b: b[2] * b[3], reverse=True)
    return panels[:max_panels]


class PopupDetector:
    SCALE_SPREAD = 0.05  # verify at +-5% around the size measured from the panel
    COARSE_STEP = 0.015
    FINE_STEP = 0.005

    def __init__(self, templates: dict[str, np.ndarray], threshold: float = 0.7):
        self.templates = {name: _smooth(tpl) for name, tpl in templates.items()}
        self.threshold = threshold
        self._resized: dict[tuple[str, int], np.ndarray] = {}
        self._panel_cache: dict[tuple, dict] = {}

    def _template(self, name: str, scale: float) -> np.ndarray | None:
        key = (name, round(scale * 1000))
        if key not in self._resized:
            tpl = self.templates[name]
            h, w = round(tpl.shape[0] * scale), round(tpl.shape[1] * scale)
            if h < 6 or w < 20:
                self._resized[key] = None
            else:
                interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
                self._resized[key] = cv2.resize(tpl, (w, h), interpolation=interp)
            if len(self._resized) > 2000:  # window got resized many times; start over
                self._resized.clear()
        return self._resized[key]

    def _best_in_roi(self, roi: np.ndarray, name: str, scales) -> tuple[float, float, tuple[int, int], tuple[int, int]]:
        best = (-1.0, 0.0, (0, 0), (0, 0))  # score, scale, location, template (w, h)
        for scale in scales:
            tpl = self._template(name, scale)
            if tpl is None or tpl.shape[0] > roi.shape[0] or tpl.shape[1] > roi.shape[1]:
                continue
            result = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(result)
            if math.isfinite(score) and score > best[0]:
                best = (score, scale, loc, (tpl.shape[1], tpl.shape[0]))
        return best

    def _match_panel(self, roi: np.ndarray, base: float) -> dict[str, tuple]:
        """Match every template in a panel: coarse pass over the size range, then refine."""
        results = {}
        steps = round(self.SCALE_SPREAD / self.COARSE_STEP)
        coarse = [base * (1 + i * self.COARSE_STEP) for i in range(-steps, steps + 1)]
        for name in self.templates:
            score, scale, _, _ = self._best_in_roi(roi, name, coarse)
            if score < 0:
                continue
            fine = [scale * (1 + i * self.FINE_STEP) for i in (-2, -1, 0, 1, 2)]
            results[name] = self._best_in_roi(roi, name, fine)
        return results

    def scan(self, bgr: np.ndarray) -> dict[str, Match]:
        """Return the best match per template inside any candidate panel (any score)."""
        gray = None
        cache = {}
        best: dict[str, Match] = {}
        for px, py, pw, ph in find_panels(bgr):
            if gray is None:
                gray = _smooth(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
            pad = max(4, round(pw * 0.03))
            x0, y0 = max(0, px - pad), max(0, py - pad)
            roi = gray[y0 : py + ph + pad, x0 : px + pw + pad]
            # A pop-up that stays open looks identical scan after scan: reuse the last result.
            key = (pw, ph, hash(gray[py : py + ph, px : px + pw].tobytes()))
            results = self._panel_cache.get(key)
            if results is None:
                results = self._match_panel(roi, pw / REFERENCE_PANEL_WIDTH)
            cache[key] = results
            for name, (score, scale, loc, (w, h)) in results.items():
                if name not in best or score > best[name].score:
                    best[name] = Match(name, TEMPLATES[name], float(score), scale, (x0 + loc[0], y0 + loc[1], w, h))
        self._panel_cache = cache
        return best

    def detect(self, bgr: np.ndarray) -> dict[str, Match]:
        """Return the pop-ups visible on the screenshot, keyed by event."""
        found: dict[str, Match] = {}
        for match in self.scan(bgr).values():
            if match.score < self.threshold:
                continue
            if match.event not in found or match.score > found[match.event].score:
                found[match.event] = match
        return found
