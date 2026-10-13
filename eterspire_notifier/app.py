"""Settings window and glue between the monitor thread and the alert outputs."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, ttk

from . import __version__, alerts, config, tray
from .capture import enable_dpi_awareness
from .detector import EVENTS, TEMPLATES, Match
from .monitor import Monitor, scan_once
from .overlay import Toasts
from .tracker import ALERT, CLOSED, PHONE, REPEAT_SOUND

EVENT_INFO = {
    "inventory_full": {
        "label": "Inventory full",
        "help": "Your bag is full of fish or logs.",
        "accent": "#e0a030",
        "tags": "package",
    },
    "spot_empty": {
        "label": "Fishing spot empty",
        "help": "The fishing spot ran out of fish. This one shows up often.",
        "accent": "#3aa0e0",
        "tags": "fishing_pole_and_fish",
    },
}
MESSAGES = {
    "inventory_full_fish": ("Inventory full", "You can't carry any more fish."),
    "inventory_full_logs": ("Inventory full", "You can't carry any more logs."),
    "spot_empty": ("Fishing spot empty", "This fishing spot has run out of fish. Find a new spot!"),
}


def describe(event: str, match: Match | None) -> tuple[str, str]:
    if match is not None and match.template in MESSAGES:
        return MESSAGES[match.template]
    return EVENT_INFO[event]["label"], ""


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = config.load()
        self.queue: queue.Queue = queue.Queue()
        self.monitor: Monitor | None = None
        self.toasts = Toasts(root)
        self.tray: tray.TrayIcon | None = None
        self._save_job = None
        self._told_about_tray = False

        root.title("Eterspire AFK Notifier")
        root.minsize(600, 560)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Unmap>", self._on_unmap)
        try:
            if sys.platform == "win32":
                # The .ico holds every size Windows needs (title bar, taskbar, Alt+Tab).
                root.iconbitmap(default=str(tray.ICON_PATH.with_suffix(".ico")))
            else:
                self._icon = tk.PhotoImage(file=str(tray.ICON_PATH))
                root.iconphoto(True, self._icon)
        except tk.TclError:
            pass

        self._build_header()
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        notebook.add(self._build_alerts_tab(notebook), text="  Alerts  ")
        notebook.add(self._build_phone_tab(notebook), text="  Phone  ")
        notebook.add(self._build_detection_tab(notebook), text="  Detection  ")
        notebook.add(self._build_app_tab(notebook), text="  App  ")
        notebook.add(self._build_log_tab(notebook), text="  Log  ")

        root.after(100, self._poll)
        self.log(f"Eterspire AFK Notifier {__version__}. Settings: {config.config_path()}")
        self._update_tray()
        if self.tray and self.settings.start_hidden:
            root.withdraw()
        if self.settings.autostart:
            self.start()

    # ------------------------------------------------------------ helpers

    def bind(self, var: tk.Variable, obj, attr: str, cast=None, on_change=None) -> tk.Variable:
        """Two-way link between a Tk variable and a settings field; changes are saved automatically."""
        var.set(getattr(obj, attr))

        def changed(*_):
            try:
                value = var.get()
                setattr(obj, attr, cast(value) if cast else value)
            except (tk.TclError, ValueError):
                return  # half-typed number; keep the old value until it's valid
            self.schedule_save()
            if on_change:
                on_change()

        var.trace_add("write", changed)
        return var

    def schedule_save(self) -> None:
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(400, self.save)

    def save(self) -> None:
        self._save_job = None
        try:
            config.save(self.settings)
        except OSError as exc:
            self.log(f"Could not save settings: {exc}")

    def log(self, text: str) -> None:
        line = f"{time.strftime('%H:%M:%S')}  {text}\n"
        if hasattr(self, "log_text"):
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

    def post(self, kind: str, payload=None) -> None:
        """Thread-safe: hand something to the UI thread."""
        self.queue.put((kind, payload))

    @staticmethod
    def spin(parent, var, low, high, width=5, increment=1):
        return ttk.Spinbox(parent, from_=low, to=high, textvariable=var, width=width, increment=increment)

    # ------------------------------------------------------------ header

    def _build_header(self) -> None:
        bar = ttk.Frame(self.root, padding=(12, 10))
        bar.pack(fill="x")
        self.dot = tk.Canvas(bar, width=14, height=14, highlightthickness=0)
        self.dot.pack(side="left")
        self.dot_id = self.dot.create_oval(2, 2, 12, 12, fill="#999", outline="")
        self.status = tk.StringVar(value="Not watching")
        ttk.Label(bar, textvariable=self.status, font=("Segoe UI", 10, "bold")).pack(side="left", padx=8)
        self.toggle_button = ttk.Button(bar, text="Start watching", command=self.toggle, width=16)
        self.toggle_button.pack(side="right")

    # ------------------------------------------------------------ alerts tab

    def _build_alerts_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=12)
        for event in EVENTS:
            info, cfg = EVENT_INFO[event], self.settings.event(event)
            box = ttk.LabelFrame(tab, text=f"  {info['label']}  ", padding=10)
            box.pack(fill="x", pady=(0, 10))
            ttk.Label(box, text=info["help"], foreground="#666").grid(row=0, column=0, columnspan=4, sticky="w")

            ttk.Checkbutton(box, text="Play a sound", variable=self.bind(tk.BooleanVar(), cfg, "sound")).grid(
                row=1, column=0, sticky="w", pady=(6, 0)
            )
            sound_label = tk.StringVar()
            ttk.Label(box, textvariable=sound_label, foreground="#666").grid(row=1, column=1, sticky="w", padx=8)
            buttons = ttk.Frame(box)
            buttons.grid(row=1, column=2, sticky="e")
            ttk.Button(buttons, text="Test", width=6, command=lambda e=event: self.play(e)).pack(side="left")
            ttk.Button(
                buttons, text="Choose…", width=9, command=lambda e=event, v=sound_label: self.choose_sound(e, v)
            ).pack(side="left", padx=4)
            ttk.Button(
                buttons, text="Default", width=8, command=lambda e=event, v=sound_label: self.reset_sound(e, v)
            ).pack(side="left")
            self._show_sound_name(event, sound_label)

            ttk.Checkbutton(
                box, text="Show a desktop notification", variable=self.bind(tk.BooleanVar(), cfg, "popup")
            ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
            ttk.Button(box, text="Test", width=6, command=lambda e=event: self.test_toast(e)).grid(
                row=2, column=2, sticky="w", pady=(4, 0)
            )

            ttk.Checkbutton(
                box, text="Send a notification to my phone", variable=self.bind(tk.BooleanVar(), cfg, "phone")
            ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
            delay = ttk.Frame(box)
            delay.grid(row=4, column=0, columnspan=3, sticky="w", padx=(24, 0))
            ttk.Label(delay, text="…only if the in-game pop-up is still open after").pack(side="left")
            self.spin(delay, self.bind(tk.IntVar(), cfg, "phone_delay", int), 0, 3600, increment=5).pack(
                side="left", padx=4
            )
            ttk.Label(delay, text="seconds (0 = right away)").pack(side="left")
            box.columnconfigure(1, weight=1)

        general = ttk.LabelFrame(tab, text="  General  ", padding=10)
        general.pack(fill="x")
        ttk.Label(general, text="Volume").grid(row=0, column=0, sticky="w")
        ttk.Scale(
            general, from_=0, to=100, variable=self.bind(tk.IntVar(), self.settings, "volume", lambda v: int(float(v)))
        ).grid(row=0, column=1, columnspan=2, sticky="ew", padx=8)
        ttk.Label(general, text="Repeat the sound every").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.spin(general, self.bind(tk.IntVar(), self.settings, "repeat_sound_every", int), 0, 3600, increment=5).grid(
            row=1, column=1, sticky="w", padx=8, pady=(6, 0)
        )
        ttk.Label(general, text="seconds while the pop-up stays open (0 = only once)").grid(
            row=1, column=2, sticky="w", pady=(6, 0)
        )
        ttk.Label(general, text="Desktop notification stays").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.spin(general, self.bind(tk.IntVar(), self.settings, "popup_seconds", int), 0, 600).grid(
            row=2, column=1, sticky="w", padx=8, pady=(6, 0)
        )
        ttk.Label(general, text="seconds (0 = until the pop-up is closed or you click it)").grid(
            row=2, column=2, sticky="w", pady=(6, 0)
        )
        general.columnconfigure(2, weight=1)
        return tab

    def _show_sound_name(self, event: str, var: tk.StringVar) -> None:
        custom = self.settings.event(event).custom_sound
        var.set(f"Sound: {Path(custom).name}" if custom else "Sound: built-in")

    def sound_path(self, event: str) -> Path:
        custom = self.settings.event(event).custom_sound
        if custom and Path(custom).is_file():
            return Path(custom)
        return alerts.builtin_sound(event)

    def play(self, event: str) -> None:
        alerts.play_sound(self.sound_path(event), self.settings.volume, on_error=lambda m: self.post("log", m))

    def choose_sound(self, event: str, var: tk.StringVar) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, title="Choose a sound", filetypes=[("WAV sound", "*.wav"), ("All files", "*.*")]
        )
        if path:
            self.settings.event(event).custom_sound = path
            self._show_sound_name(event, var)
            self.schedule_save()
            self.play(event)

    def reset_sound(self, event: str, var: tk.StringVar) -> None:
        self.settings.event(event).custom_sound = ""
        self._show_sound_name(event, var)
        self.schedule_save()

    def test_toast(self, event: str) -> None:
        title, message = describe(event, None)
        self.toasts.show(
            event, title, message or "This is how alerts will look.", EVENT_INFO[event]["accent"], self.settings.popup_seconds or 8
        )

    # ------------------------------------------------------------ phone tab

    def _build_phone_tab(self, parent) -> ttk.Frame:
        phone = self.settings.phone
        tab = ttk.Frame(parent, padding=12)
        ttk.Label(
            tab,
            text="Optional: get alerts on your phone while you're away from the PC. Tick one or more\n"
            "services and set them up once, then tick \"Send a notification to my phone\" in the Alerts tab.",
            justify="left",
        ).pack(anchor="w")

        test = ttk.Frame(tab)
        test.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(test, text="Test all ticked services", command=self.test_phone).pack(side="left")
        self.phone_result = tk.StringVar()
        ttk.Label(test, textvariable=self.phone_result, wraplength=400, justify="left").pack(side="left", padx=10)

        self.service_tabs = ttk.Notebook(tab)
        self.service_tabs.pack(fill="both", expand=True, pady=(8, 0))
        self.service_pages = {}
        builders = {"ntfy": self._build_ntfy, "discord": self._build_discord, "telegram": self._build_telegram}
        hints = {
            "ntfy": "Use ntfy (recommended: free app, no account needed)",
            "discord": "Use Discord (a webhook in your own server)",
            "telegram": "Use Telegram (your own bot)",
        }
        for service, build in builders.items():
            page = ttk.Frame(self.service_tabs, padding=10)
            top = ttk.Frame(page)
            top.pack(fill="x", pady=(0, 8))
            ttk.Checkbutton(
                top,
                text=hints[service],
                variable=self.bind(tk.BooleanVar(), phone, f"use_{service}", on_change=self._update_service_tabs),
            ).pack(side="left")
            ttk.Button(top, text="Send a test", command=lambda sv=service: self.test_phone([sv])).pack(side="right")
            build(page).pack(fill="both", expand=True)
            self.service_tabs.add(page)
            self.service_pages[service] = page
        self._update_service_tabs()
        return tab

    def _update_service_tabs(self) -> None:
        """Tab titles show which services are in use."""
        for service, page in self.service_pages.items():
            used = getattr(self.settings.phone, f"use_{service}")
            self.service_tabs.tab(page, text=f"  {'✔ ' if used else ''}{alerts.SERVICES[service]}  ")

    def _build_ntfy(self, parent) -> ttk.Frame:
        phone = self.settings.phone
        frame = ttk.Frame(parent)
        left = ttk.Frame(frame)
        left.pack(side="left", fill="both", expand=True)
        steps = (
            "1. Install the free \"ntfy\" app (Google Play, F-Droid or App Store).\n"
            "2. In the app tap +, and subscribe to the topic below\n"
            "    (or scan the QR code with your phone camera).\n"
            "3. Click \"Send a test\"."
        )
        ttk.Label(left, text=steps, justify="left").pack(anchor="w")

        row = ttk.Frame(left)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text="Topic").pack(side="left")
        topic = self.bind(tk.StringVar(), phone, "ntfy_topic", str.strip, on_change=self._draw_qr)
        ttk.Entry(row, textvariable=topic, width=28).pack(side="left", padx=6)
        ttk.Button(row, text="Copy", width=6, command=lambda: self.copy(phone.ntfy_topic)).pack(side="left")
        ttk.Button(row, text="New", width=6, command=lambda: topic.set(config.new_ntfy_topic())).pack(side="left", padx=4)
        ttk.Label(
            left,
            text="Anyone who knows the topic name can read its messages, so keep the random name.",
            foreground="#666",
            wraplength=330,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        row = ttk.Frame(left)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text="Server").pack(side="left")
        ttk.Entry(
            row, textvariable=self.bind(tk.StringVar(), phone, "ntfy_server", str.strip, on_change=self._draw_qr), width=28
        ).pack(side="left", padx=6)
        ttk.Label(row, text="(leave as is)", foreground="#666").pack(side="left")

        self.qr = tk.Canvas(frame, width=150, height=150, bg="white", highlightthickness=0, cursor="hand2")
        self.qr.pack(side="right", padx=(10, 0), anchor="n")
        self.qr.bind("<Button-1>", lambda _e: webbrowser.open(alerts.ntfy_url(phone)))
        self._draw_qr()
        return frame

    def _draw_qr(self) -> None:
        canvas = self.qr
        canvas.delete("all")
        try:
            import qrcode
        except ImportError:
            canvas.create_text(75, 75, text="(QR needs the\n'qrcode' package)", justify="center")
            return
        code = qrcode.QRCode(border=2)
        code.add_data(alerts.ntfy_url(self.settings.phone))
        code.make(fit=True)
        matrix = code.get_matrix()
        cell = max(1, 150 // len(matrix))
        offset = (150 - cell * len(matrix)) // 2
        for y, line in enumerate(matrix):
            for x, dark in enumerate(line):
                if dark:
                    x0, y0 = offset + x * cell, offset + y * cell
                    canvas.create_rectangle(x0, y0, x0 + cell, y0 + cell, fill="black", outline="")

    def _build_discord(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)
        steps = (
            "1. In your own Discord server: Server Settings → Integrations → Webhooks → New Webhook.\n"
            "2. Pick a channel, click \"Copy Webhook URL\" and paste it below.\n"
            "3. Make sure Discord notifications for that channel are on in the phone app."
        )
        ttk.Label(frame, text=steps, justify="left", wraplength=540).pack(anchor="w")
        ttk.Label(frame, text="Webhook URL").pack(anchor="w", pady=(10, 0))
        ttk.Entry(
            frame, textvariable=self.bind(tk.StringVar(), self.settings.phone, "discord_webhook", str.strip), width=70
        ).pack(fill="x")
        return frame

    def _build_telegram(self, parent) -> ttk.Frame:
        phone = self.settings.phone
        frame = ttk.Frame(parent)
        steps = (
            "1. In Telegram, open @BotFather, send /newbot and follow the steps.\n"
            "2. Paste the bot token it gives you below.\n"
            "3. Open your new bot, press Start (or send it any message), then click \"Find my chat ID\"."
        )
        ttk.Label(frame, text=steps, justify="left", wraplength=540).pack(anchor="w")
        grid = ttk.Frame(frame)
        grid.pack(fill="x", pady=(10, 0))
        ttk.Label(grid, text="Bot token").grid(row=0, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.bind(tk.StringVar(), phone, "telegram_token", str.strip), width=50, show="•").grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Label(grid, text="Chat ID").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.chat_id = self.bind(tk.StringVar(), phone, "telegram_chat_id", str.strip)
        ttk.Entry(grid, textvariable=self.chat_id, width=20).grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))
        ttk.Button(grid, text="Find my chat ID", command=self.find_chat_id).grid(row=1, column=2, pady=(6, 0))
        grid.columnconfigure(1, weight=1)
        return frame

    def copy(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.phone_result.set("Copied!")

    def test_phone(self, services: list[str] | None = None) -> None:
        """Send a test with the given services (default: the ticked ones)."""
        self._test_results = {}
        sent = alerts.send_phone_async(
            self.settings.phone,
            "Eterspire Notifier",
            "Test notification: phone alerts are working!",
            tags="white_check_mark",
            services=services,
            on_done=lambda service, error: self.post("phone_test", (service, error)),
        )
        self._test_pending = list(sent)
        self.phone_result.set("Sending…" if sent else "Tick at least one service first.")

    def _show_test_results(self) -> None:
        lines = []
        for service in self._test_pending:
            name = alerts.SERVICES[service]
            if service not in self._test_results:
                lines.append(f"{name}: sending…")
            elif self._test_results[service]:
                lines.append(f"{name}: failed, {self._test_results[service]}")
            else:
                lines.append(f"{name}: sent! Check your phone.")
        self.phone_result.set("\n".join(lines))

    def find_chat_id(self) -> None:
        token = self.settings.phone.telegram_token
        self.phone_result.set("Looking for your chat…")

        def run():
            try:
                self.post("chat_id", (alerts.telegram_find_chat_id(token), None))
            except alerts.PhoneError as exc:
                self.post("chat_id", (None, str(exc)))

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------ detection tab

    def _build_detection_tab(self, parent) -> ttk.Frame:
        s = self.settings
        tab = ttk.Frame(parent, padding=12)
        ttk.Label(
            tab,
            text="The app looks at the game window for its pop-ups. The game can stay behind other\n"
            "windows, but it must not be minimized.",
            justify="left",
        ).pack(anchor="w")

        box = ttk.LabelFrame(tab, text="  Where to look  ", padding=10)
        box.pack(fill="x", pady=10)
        ttk.Checkbutton(
            box, text="Only watch the game window, titled:", variable=self.bind(tk.BooleanVar(), s, "capture_window")
        ).grid(row=0, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.bind(tk.StringVar(), s, "window_title"), width=24).grid(row=0, column=1, padx=6)
        ttk.Label(
            box, text="If the window can't be found, all screens are watched instead.", foreground="#666"
        ).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(box, text="Check the screen every").grid(row=2, column=0, sticky="w", pady=(8, 0))
        row = ttk.Frame(box)
        row.grid(row=2, column=1, sticky="w", padx=6, pady=(8, 0))
        self.spin(row, self.bind(tk.DoubleVar(), s, "scan_interval", lambda v: max(0.3, float(v))), 0.3, 10, increment=0.5).pack(
            side="left"
        )
        ttk.Label(row, text="seconds").pack(side="left", padx=4)

        box = ttk.LabelFrame(tab, text="  Matching  ", padding=10)
        box.pack(fill="x")
        threshold_text = tk.StringVar()

        def show_threshold():
            threshold_text.set(f"{s.match_threshold:.2f}")

        ttk.Label(box, text="Strictness").grid(row=0, column=0, sticky="w")
        ttk.Scale(
            box,
            from_=0.5,
            to=0.95,
            variable=self.bind(tk.DoubleVar(), s, "match_threshold", lambda v: round(float(v), 2), show_threshold),
        ).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Label(box, textvariable=threshold_text, width=5).grid(row=0, column=2)
        show_threshold()
        ttk.Label(
            box,
            text="Lower it if a pop-up is missed, raise it if alerts fire for no reason.",
            foreground="#666",
        ).grid(row=1, column=0, columnspan=3, sticky="w")
        box.columnconfigure(1, weight=1)

        row = ttk.Frame(tab)
        row.pack(fill="x", pady=10)
        ttk.Button(row, text="Test detection now", command=self.test_detection).pack(side="left")
        ttk.Button(row, text="Open custom templates folder", command=self.open_templates).pack(side="left", padx=6)
        ttk.Button(row, text="Reload templates", command=self.reload_templates).pack(side="left")
        self.scan_result = tk.StringVar(value="Open a pop-up in the game, then click \"Test detection now\".")
        ttk.Label(tab, textvariable=self.scan_result, justify="left", font=("Consolas", 9)).pack(anchor="w")
        return tab

    def test_detection(self) -> None:
        self.scan_result.set("Scanning…")

        def run():
            try:
                self.post("scan", scan_once(self.settings))
            except Exception as exc:  # noqa: BLE001
                self.post("scan", (f"Scan failed: {exc}", {}))

        threading.Thread(target=run, daemon=True).start()

    def open_templates(self) -> None:
        folder = config.user_templates_dir()
        self.log(
            f"Custom templates: put a PNG named {', '.join(n + '.png' for n in TEMPLATES)} in {folder} "
            "to replace the built-in one, then click Reload templates."
        )
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(folder)], check=False)

    def reload_templates(self) -> None:
        if self.monitor:
            self.monitor.reload_templates()
        self.log("Templates reloaded.")

    # ------------------------------------------------------------ app tab

    def _build_app_tab(self, parent) -> ttk.Frame:
        s = self.settings
        tab = ttk.Frame(parent, padding=12)
        box = ttk.LabelFrame(tab, text="  Startup  ", padding=10)
        box.pack(fill="x")
        ttk.Checkbutton(
            box, text="Start watching as soon as the app opens", variable=self.bind(tk.BooleanVar(), s, "autostart")
        ).pack(anchor="w")

        box = ttk.LabelFrame(tab, text="  Notification area (hidden icons)  ", padding=10)
        box.pack(fill="x", pady=10)
        hide = ttk.Checkbutton(
            box,
            text="Minimizing or closing the window hides the app in the notification area",
            variable=self.bind(tk.BooleanVar(), s, "hide_to_tray", on_change=self._update_tray),
        )
        hide.pack(anchor="w")
        self.start_hidden_check = ttk.Checkbutton(
            box, text="Start hidden in the notification area", variable=self.bind(tk.BooleanVar(), s, "start_hidden")
        )
        self.start_hidden_check.pack(anchor="w", padx=(24, 0), pady=(4, 0))
        ttk.Label(
            box,
            text="The app keeps watching while hidden. Its icon is under the ^ arrow next to the clock:\n"
            "click it to open this window again, right-click it to start/stop watching or to quit.",
            foreground="#666",
            justify="left",
        ).pack(anchor="w", pady=(8, 0))
        if not tray.available():
            hide.state(["disabled"])
            ttk.Label(box, text="Not available: the 'pystray' package is missing.", foreground="#b00").pack(anchor="w")
        self._update_start_hidden_state()
        return tab

    def _update_start_hidden_state(self) -> None:
        if hasattr(self, "start_hidden_check"):
            enabled = self.settings.hide_to_tray and tray.available()
            self.start_hidden_check.state(["!disabled"] if enabled else ["disabled"])

    def _update_tray(self) -> None:
        """Create or remove the tray icon to match the setting."""
        self._update_start_hidden_state()
        wanted = self.settings.hide_to_tray and tray.available()
        if wanted and not self.tray:
            try:
                self.tray = tray.TrayIcon(
                    on_show=lambda: self.post("tray_show"),
                    on_toggle=lambda: self.post("tray_toggle"),
                    on_quit=lambda: self.post("tray_quit"),
                    is_watching=lambda: self.monitor is not None,
                )
                self.tray.set_tooltip(f"Eterspire AFK Notifier: {self.status.get()}")
            except Exception as exc:  # noqa: BLE001 - no tray icon is not fatal
                self.tray = None
                self.log(f"Could not create the tray icon: {exc}")
        elif not wanted and self.tray:
            self.tray.stop()
            self.tray = None
            self.show_window()

    def hide_window(self) -> None:
        self.root.withdraw()
        if not self._told_about_tray:
            self._told_about_tray = True
            self.toasts.show(
                "tray",
                "Still watching",
                "Eterspire Notifier is hidden under the ^ arrow next to the clock. Click its icon to open it.",
                "#888",
                6,
            )

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _on_unmap(self, event) -> None:
        # Minimize button: hide in the notification area instead of the taskbar.
        if event.widget is self.root and self.tray and self.root.state() == "iconic":
            self.root.after(0, self.hide_window)

    def on_close(self) -> None:
        if self.tray:
            self.hide_window()
        else:
            self.quit()

    # ------------------------------------------------------------ log tab

    def _build_log_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=6)
        self.log_text = tk.Text(tab, height=10, state="disabled", wrap="word", font=("Consolas", 9), relief="flat")
        scroll = ttk.Scrollbar(tab, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)
        return tab

    # ------------------------------------------------------------ monitoring

    def toggle(self) -> None:
        self.stop() if self.monitor else self.start()

    def start(self) -> None:
        if self.monitor:
            return
        self.monitor = Monitor(self.settings, self.post)
        self.monitor.start()
        self.toggle_button.configure(text="Stop watching")
        self.dot.itemconfigure(self.dot_id, fill="#3c3")
        self._set_status("Starting…")
        self.log("Started watching.")

    def stop(self) -> None:
        if not self.monitor:
            return
        self.monitor.stop()
        self.monitor = None
        self.toggle_button.configure(text="Start watching")
        self.dot.itemconfigure(self.dot_id, fill="#999")
        self._set_status("Not watching")
        for event in EVENTS:
            self.toasts.close(event)
        self.log("Stopped watching.")

    def _set_status(self, text: str) -> None:
        self.status.set(text)
        if self.tray:
            self.tray.set_tooltip(f"Eterspire AFK Notifier: {text}")

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle(self, kind: str, payload) -> None:
        if kind == "status":
            if self.monitor:
                self._set_status(payload)
            self.log(payload)
        elif kind == "tray_show":
            self.show_window()
        elif kind == "tray_toggle":
            self.toggle()
        elif kind == "tray_quit":
            self.quit()
        elif kind in ("log", "error"):
            self.log(payload)
        elif kind == "action":
            self._on_action(*payload)
        elif kind == "phone_test":
            service, error = payload
            self._test_results[service] = error
            self._show_test_results()
        elif kind == "chat_id":
            chat_id, error = payload
            if chat_id:
                self.chat_id.set(chat_id)
                self.phone_result.set("Chat ID found. Now click \"Send a test\".")
            else:
                self.phone_result.set(error)
        elif kind == "scan":
            status, matches = payload
            lines = [status]
            for name in TEMPLATES:
                if name in matches:
                    m = matches[name]
                    verdict = "FOUND" if m.score >= self.settings.match_threshold else "not found"
                    lines.append(f"{name:<22} score {m.score:.2f}  size x{m.scale:.2f}  {verdict}")
                else:
                    lines.append(f"{name:<22} no pop-up shaped panel on screen")
            self.scan_result.set("\n".join(lines))

    def _on_action(self, event: str, action: str, match: Match | None) -> None:
        cfg = self.settings.event(event)
        title, message = describe(event, match)
        if action == ALERT:
            self.log(f"Pop-up: {message or title}")
            if cfg.sound:
                self.play(event)
            if cfg.popup:
                self.toasts.show(event, title, message, EVENT_INFO[event]["accent"], self.settings.popup_seconds)
        elif action == REPEAT_SOUND:
            self.play(event)
        elif action == PHONE:
            text = message
            if cfg.phone_delay > 0:
                text += f" (pop-up open for {cfg.phone_delay}s)"
            sent = alerts.send_phone_async(
                self.settings.phone,
                f"Eterspire: {title}",
                text,
                tags=EVENT_INFO[event]["tags"],
                urgent=True,
                on_done=lambda service, error: error
                and self.post("error", f"{alerts.SERVICES[service]} notification failed: {error}"),
            )
            if sent:
                self.log(f"Sending phone notification ({', '.join(alerts.SERVICES[x] for x in sent)}): {title}")
            else:
                self.log("No phone notification sent: no service is ticked in the Phone tab.")
        elif action == CLOSED:
            self.toasts.close(event)
            self.log(f"Pop-up closed: {title}")

    def quit(self) -> None:
        self.stop()
        if self.tray:
            self.tray.stop()
            self.tray = None
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self.save()
        self.root.destroy()


def main() -> None:
    enable_dpi_awareness()
    if sys.platform == "win32":
        import ctypes

        # Own taskbar identity: without it, running from source shows Python's icon in the taskbar.
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Eterspire.AFKNotifier")
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista" if sys.platform == "win32" else "clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
