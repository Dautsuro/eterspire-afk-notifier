"""Captures the game window (even when other windows cover it) or the whole screen."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import cv2
import mss
import numpy as np

_MSS = getattr(mss, "MSS", None) or mss.mss


@dataclass
class Target:
    region: dict  # mss region: left, top, width, height (screen pixels)
    hwnd: int | None = None  # game window handle, captured directly when set


def enable_dpi_awareness() -> None:
    """Make window coordinates and screenshots use real pixels on scaled (125%, 150%...) displays."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes as W

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _ENUM_PROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    for _name, _args, _res in [
        ("EnumWindows", [_ENUM_PROC, W.LPARAM], W.BOOL),
        ("IsWindowVisible", [W.HWND], W.BOOL),
        ("IsIconic", [W.HWND], W.BOOL),
        ("GetWindowTextLengthW", [W.HWND], ctypes.c_int),
        ("GetWindowTextW", [W.HWND, W.LPWSTR, ctypes.c_int], ctypes.c_int),
        ("GetWindowThreadProcessId", [W.HWND, ctypes.POINTER(W.DWORD)], W.DWORD),
        ("GetClientRect", [W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
        ("ClientToScreen", [W.HWND, ctypes.POINTER(W.POINT)], W.BOOL),
        ("GetDC", [W.HWND], W.HDC),
        ("ReleaseDC", [W.HWND, W.HDC], ctypes.c_int),
        ("PrintWindow", [W.HWND, W.HDC, W.UINT], W.BOOL),
    ]:
        _fn = getattr(_user32, _name)
        _fn.argtypes, _fn.restype = _args, _res
    for _name, _args, _res in [
        ("CreateCompatibleDC", [W.HDC], W.HDC),
        ("CreateCompatibleBitmap", [W.HDC, ctypes.c_int, ctypes.c_int], W.HBITMAP),
        ("SelectObject", [W.HDC, W.HGDIOBJ], W.HGDIOBJ),
        ("DeleteObject", [W.HGDIOBJ], W.BOOL),
        ("DeleteDC", [W.HDC], W.BOOL),
        ("GetDIBits", [W.HDC, W.HBITMAP, W.UINT, W.UINT, ctypes.c_void_p, ctypes.c_void_p, W.UINT], ctypes.c_int),
    ]:
        _fn = getattr(_gdi32, _name)
        _fn.argtypes, _fn.restype = _args, _res

    class _BitmapInfoHeader(ctypes.Structure):
        _fields_ = [
            ("biSize", W.DWORD),
            ("biWidth", W.LONG),
            ("biHeight", W.LONG),
            ("biPlanes", W.WORD),
            ("biBitCount", W.WORD),
            ("biCompression", W.DWORD),
            ("biSizeImage", W.DWORD),
            ("biXPelsPerMeter", W.LONG),
            ("biYPelsPerMeter", W.LONG),
            ("biClrUsed", W.DWORD),
            ("biClrImportant", W.DWORD),
        ]


def _client_region(hwnd) -> dict:
    rect = W.RECT()
    _user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = W.POINT(0, 0)
    _user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return {"left": origin.x, "top": origin.y, "width": rect.right, "height": rect.bottom}


def find_window(title: str) -> tuple[Target | None, str]:
    """Locate the game window by title.

    Returns the capture target (or None) and a short status text. A window whose title is
    exactly ``title`` wins over one that merely contains it; among equals the biggest wins.
    """
    if sys.platform != "win32":
        return None, "window search is only available on Windows"
    wanted = title.strip().lower()
    if not wanted:
        return None, "no window title set"
    own_pid = os.getpid()
    candidates = []

    @_ENUM_PROC
    def callback(hwnd, _):
        if not _user32.IsWindowVisible(hwnd):
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buf, length + 1)
        name = buf.value.strip()
        if wanted not in name.lower():
            return True
        pid = W.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != own_pid:  # skip our own window, "Eterspire AFK Notifier"
            candidates.append((name.lower() == wanted, hwnd, name))
        return True

    _user32.EnumWindows(callback, 0)
    if not candidates:
        return None, f'no window called "{title}" found'

    best, best_key = None, None
    for exact, hwnd, name in candidates:
        minimized = bool(_user32.IsIconic(hwnd))
        region = _client_region(hwnd)
        key = (not minimized, exact, region["width"] * region["height"])
        if best_key is None or key > best_key:
            best, best_key = (hwnd, name, region, minimized), key
    hwnd, name, region, minimized = best
    if minimized:
        return None, f'"{name}" is minimized'
    if region["width"] < 50 or region["height"] < 50:
        return None, f'"{name}" is too small'
    return Target(region, hwnd), f'"{name}" window ({region["width"]}x{region["height"]})'


def _print_window(hwnd, width: int, height: int) -> np.ndarray | None:
    """Ask the window to draw itself into a bitmap. Works while other windows cover it."""
    PW_CLIENTONLY, PW_RENDERFULLCONTENT = 1, 2
    hdc = _user32.GetDC(hwnd)
    if not hdc:
        return None
    mem_dc = _gdi32.CreateCompatibleDC(hdc)
    bitmap = _gdi32.CreateCompatibleBitmap(hdc, width, height)
    old = _gdi32.SelectObject(mem_dc, bitmap)
    try:
        if not _user32.PrintWindow(hwnd, mem_dc, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            return None
        header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = np.empty((height, width, 4), dtype=np.uint8)
        if _gdi32.GetDIBits(mem_dc, bitmap, 0, height, pixels.ctypes.data, ctypes.byref(header), 0) != height:
            return None
        return pixels[..., :3].copy()
    finally:
        _gdi32.SelectObject(mem_dc, old)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(hwnd, hdc)


class ScreenGrabber:
    """Takes BGR screenshots. Create and use it on a single thread."""

    def __init__(self):
        self._sct = _MSS()

    def all_screens(self) -> Target:
        return Target(dict(self._sct.monitors[0]))

    def grab(self, target: Target) -> np.ndarray:
        if target.hwnd is not None:
            image = _print_window(target.hwnd, target.region["width"], target.region["height"])
            # Some graphics drivers hand back a black picture; then fall back to what's on screen.
            if image is not None and image.max() > 0:
                return image
        shot = self._sct.grab(target.region)
        return cv2.cvtColor(np.asarray(shot), cv2.COLOR_BGRA2BGR)

    def close(self) -> None:
        self._sct.close()
