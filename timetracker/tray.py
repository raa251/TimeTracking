"""Tray-Icon und Kontextmenü (pystray)."""
from __future__ import annotations

import logging

import pystray
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem

from . import autostart

log = logging.getLogger(__name__)


def make_image(paused: bool = False, size: int = 64) -> Image.Image:
    """Zeichnet das Uhr-Icon (blau = aktiv, grau = pausiert) in beliebiger Größe."""
    s = 256
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = (120, 122, 130, 255) if paused else (37, 99, 235, 255)
    d.ellipse((6, 6, s - 6, s - 6), fill=bg)
    c = s // 2
    r = 86
    d.ellipse((c - r, c - r, c + r, c + r), outline=(255, 255, 255, 235), width=12)
    d.line((c, c, c, c - 58), fill=(255, 255, 255, 255), width=16)
    d.line((c, c, c + 42, c + 24), fill=(255, 255, 255, 255), width=16)
    d.ellipse((c - 12, c - 12, c + 12, c + 12), fill=(255, 255, 255, 255))
    if size != s:
        img = img.resize((size, size), Image.LANCZOS)
    return img


def save_ico(path: str) -> None:
    """Erzeugt eine Multi-Resolution-.ico-Datei für die PyInstaller-.exe."""
    base = make_image(False, 256)
    base.save(path, format="ICO",
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


class Tray:
    def __init__(self, app):
        self.app = app
        self._status_text = "TimeTracker startet …"
        self._paused_shown = False
        self.icon = pystray.Icon(
            "timetracker",
            icon=make_image(False),
            title="TimeTracker",
            menu=self._menu(),
        )

    # -- Menüaufbau -------------------------------------------------
    def _menu(self) -> Menu:
        return Menu(
            MenuItem(lambda item: self._status_text, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Dashboard öffnen", lambda: self.app.open_dashboard(), default=True),
            MenuItem("Einstellungen …", lambda: self.app.open_settings()),
            MenuItem(
                "Tracking pausiert",
                lambda: self.app.toggle_pause(),
                checked=lambda item: self.app.is_paused(),
            ),
            Menu.SEPARATOR,
            MenuItem("Export der letzten 7 Tage", Menu(
                MenuItem("als CSV …", lambda: self.app.export("csv")),
                MenuItem("als JSON …", lambda: self.app.export("json")),
            )),
            MenuItem(
                "Mit Windows starten",
                lambda: self.app.toggle_autostart(),
                checked=lambda item: autostart.is_enabled(),
            ),
            MenuItem("Datenordner öffnen", lambda: self.app.open_folder()),
            Menu.SEPARATOR,
            MenuItem("Beenden", lambda: self.app.quit()),
        )

    # -- Laufzeit-Updates ----------------------------------------
    def set_status(self, active_today_seconds: float, paused: bool) -> None:
        from .reporting import fmt_duration

        if paused:
            self._status_text = "⏸  Tracking pausiert"
            self.icon.title = "TimeTracker – pausiert"
        else:
            human = fmt_duration(active_today_seconds, short=True)
            self._status_text = f"▶  Heute aktiv: {human}"
            self.icon.title = f"TimeTracker – heute {human} aktiv"
        try:
            if paused != self._paused_shown:
                self.icon.icon = make_image(paused)
                self._paused_shown = paused
            self.icon.update_menu()
        except Exception:  # noqa: BLE001
            pass

    def notify(self, message: str, title: str = "TimeTracker") -> None:
        try:
            self.icon.notify(message, title)
        except Exception:  # noqa: BLE001
            log.info("notify: %s – %s", title, message)

    def run(self) -> None:
        self.icon.run()

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:  # noqa: BLE001
            pass
