"""Icon in the notification area (the taskbar's hidden icons)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

ICON_PATH = Path(__file__).parent / "assets" / "icon.png"

try:
    import pystray
    from PIL import Image
except ImportError:  # the app still works without a tray icon
    pystray = None


def available() -> bool:
    return pystray is not None


class TrayIcon:
    """Runs on its own thread: the callbacks are called from that thread, not Tk's."""

    def __init__(
        self,
        on_show: Callable[[], None],
        on_toggle: Callable[[], None],
        on_quit: Callable[[], None],
        is_watching: Callable[[], bool],
    ):
        menu = pystray.Menu(
            pystray.MenuItem("Open Eterspire Notifier", lambda: on_show(), default=True),
            pystray.MenuItem(lambda _item: "Stop watching" if is_watching() else "Start watching", lambda: on_toggle()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: on_quit()),
        )
        self._icon = pystray.Icon("EterspireNotifier", Image.open(ICON_PATH), "Eterspire AFK Notifier", menu)
        self._icon.run_detached()

    def set_tooltip(self, text: str) -> None:
        self._icon.title = text[:127]  # Windows tooltip limit
        self._icon.update_menu()  # refresh the Start/Stop label

    def stop(self) -> None:
        self._icon.stop()
