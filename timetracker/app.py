"""Orchestrierung: Tracker-Thread + Tray-Icon + Dashboard-Fenster."""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from datetime import datetime

from . import autostart
from .config import DATA_DIR, DB_PATH, EXPORT_DIR, LOG_PATH, Config
from .database import Database
from .tracker import Tracker

log = logging.getLogger("timetracker")


def setup_logging(verbose: bool = False) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    if sys.stdout and sys.stdout.isatty():
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)


class Application:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.db = Database(DB_PATH)
        self.shutdown_event = threading.Event()

        self.tracker = Tracker(self.db, self.config, status_callback=self._on_status)
        self._dashboard = None
        self._dashboard_thread: threading.Thread | None = None
        self._quitting = False

        from .tray import Tray  # verzögert: pystray importiert erst hier
        self.tray = Tray(self)

    # -- Start / Stop ------------------------------------------------
    def run(self) -> None:
        log.info("TimeTracker %s startet – Daten in %s", _version(), DATA_DIR)
        if self.config.get("autostart") and not autostart.is_enabled():
            autostart.enable()
        self.tracker.start()
        try:
            self.tray.run()  # blockiert im Tray-Message-Loop (Hauptthread)
        finally:
            self._teardown()

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        log.info("Beenden angefordert")
        self.shutdown_event.set()
        self.tracker.stop()
        self.tracker.join(timeout=6)
        if self._dashboard_thread and self._dashboard_thread.is_alive():
            self._dashboard_thread.join(timeout=3)
        self.tray.stop()

    def _teardown(self) -> None:
        try:
            self.db.close()
        except Exception:  # noqa: BLE001
            pass
        log.info("Beendet.")

    # -- Tray-Callbacks -------------------------------------------
    def _on_status(self, active_today: float, paused: bool) -> None:
        try:
            self.tray.set_status(active_today, paused)
        except Exception:  # noqa: BLE001
            log.exception("Statusaktualisierung fehlgeschlagen")

    def open_dashboard(self) -> None:
        if self._dashboard_thread and self._dashboard_thread.is_alive() and self._dashboard:
            try:
                root = self._dashboard.root
                root.after(0, lambda: (root.deiconify(), root.lift(), root.focus_force()))
            except Exception:  # noqa: BLE001
                pass
            return

        def _run() -> None:
            from .dashboard import Dashboard
            try:
                self._dashboard = Dashboard(self.db, self.config, self.shutdown_event)
                self._dashboard.run()
            except Exception:  # noqa: BLE001
                log.exception("Dashboard-Thread abgestürzt")
            finally:
                self._dashboard = None

        self._dashboard_thread = threading.Thread(target=_run, name="Dashboard", daemon=True)
        self._dashboard_thread.start()

    def toggle_pause(self) -> None:
        paused = self.tracker.toggle_pause()
        self.tray.notify("Tracking pausiert." if paused else "Tracking läuft wieder.")

    def is_paused(self) -> bool:
        return self.tracker.paused

    def export(self, fmt: str) -> None:
        from . import reporting
        days = reporting.last_n_days(7)
        segments = reporting.load_range(self.db, days[0], days[-1])
        if not segments:
            self.tray.notify("Keine Daten für die letzten 7 Tage.")
            return
        content = (reporting.export_csv(segments) if fmt == "csv"
                   else reporting.export_json(segments, self.config))
        target = EXPORT_DIR / f"timetracker_7tage_{datetime.now():%Y%m%d_%H%M%S}.{fmt}"
        encoding = "utf-8-sig" if fmt == "csv" else "utf-8"
        target.write_text(content, encoding=encoding)
        self.tray.notify(f"Export gespeichert:\n{target.name}")
        self.open_folder()

    def toggle_autostart(self) -> None:
        enabled = autostart.toggle()
        self.config.set("autostart", enabled)
        self.tray.notify("Autostart aktiviert." if enabled else "Autostart deaktiviert.")

    def open_folder(self) -> None:
        import os
        import subprocess
        try:
            os.startfile(str(DATA_DIR))  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            subprocess.Popen(["explorer", str(DATA_DIR)])


def _version() -> str:
    from . import __version__
    return __version__


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    from . import single_instance
    if not single_instance.acquire():
        log.info("Bereits eine Instanz aktiv – Start abgebrochen.")
        single_instance.notify_already_running()
        return 0
    try:
        Application().run()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:  # noqa: BLE001
        log.exception("Unbehandelter Fehler")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
