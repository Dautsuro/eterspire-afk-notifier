"""Small desktop notification in the bottom-right corner that never steals focus from the game."""

from __future__ import annotations

import sys
import tkinter as tk

BG = "#2b1d14"
FG = "#f4e9d8"
MUTED = "#c9b79c"
WIDTH = 330
MARGIN = 16
TASKBAR = 48


def _show_without_focus(window: tk.Toplevel) -> None:
    """Show the toast without taking the keyboard focus from the game, and keep it off the taskbar."""
    if sys.platform != "win32":
        window.deiconify()
        return
    import ctypes

    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_TOPMOST = 0x00000008
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
    previous = user32.GetForegroundWindow()
    window.deiconify()
    window.update_idletasks()
    # Tk may activate the window when showing it; hand the focus straight back to the game.
    if previous and user32.GetForegroundWindow() != previous:
        user32.SetForegroundWindow(previous)


class Toasts:
    """Shows one toast per key; a new toast for the same key replaces the old one."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self._open: dict[str, tk.Toplevel] = {}

    def show(self, key: str, title: str, message: str, accent: str, seconds: int) -> None:
        self.close(key)
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.95)
        except tk.TclError:
            pass
        win.configure(bg=accent)

        body = tk.Frame(win, bg=BG, padx=14, pady=10)
        body.pack(fill="both", expand=True, padx=(5, 0))
        tk.Label(body, text=title, bg=BG, fg=FG, font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
        tk.Label(
            body, text=message, bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w", justify="left", wraplength=WIDTH - 40
        ).pack(fill="x", pady=(2, 0))
        for widget in (win, body, *body.winfo_children()):
            widget.bind("<Button-1>", lambda _e, k=key: self.close(k))

        win.update_idletasks()
        height = win.winfo_reqheight()
        slot = len(self._open)
        x = win.winfo_screenwidth() - WIDTH - MARGIN
        y = win.winfo_screenheight() - TASKBAR - MARGIN - (height + 8) * (slot + 1)
        win.geometry(f"{WIDTH}x{height}+{x}+{y}")
        _show_without_focus(win)
        self._open[key] = win
        if seconds > 0:
            win.after(seconds * 1000, lambda k=key, w=win: self._expire(k, w))

    def _expire(self, key: str, win: tk.Toplevel) -> None:
        if self._open.get(key) is win:
            self.close(key)

    def close(self, key: str) -> None:
        win = self._open.pop(key, None)
        if win is not None:
            win.destroy()
