"""Der Hintergrund-Thread, der das aktive Fenster pollt und Segmente schreibt."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, time as dtime

from . import winapi
from .classify import categorize, friendly_app_name, is_private, parse_document
from .config import Config
from .database import Database

log = logging.getLogger(__name__)

STATE_ACTIVE = "active"
STATE_IDLE = "idle"
STATE_LOCKED = "locked"


def _midnight_epoch(dt: datetime) -> float:
    return datetime.combine(dt.date(), dtime.min).timestamp()


class Tracker(threading.Thread):
    """Erfasst kontinuierlich das aktive Fenster.

    ``status_callback(active_seconds_today: float, paused: bool)`` wird ~alle
    30 s aufgerufen, damit das Tray-Icon Tooltip/Menü aktualisieren kann.
    """

    def __init__(self, db: Database, config: Config, status_callback=None):
        super().__init__(name="TimeTracker-Tracker", daemon=True)
        self.db = db
        self.config = config
        self.status_callback = status_callback

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._seg: dict | None = None          # aktuell offenes Segment
        self._last_purge = ""
        self._last_status = 0.0

    # -- öffentliche Steuerung -------------------------------------------
    def stop(self) -> None:
        self._stop_event.set()

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def toggle_pause(self) -> bool:
        if self._pause_event.is_set():
            self._pause_event.clear()
        else:
            self._pause_event.set()
        self._emit_status(force=True)
        return self._pause_event.is_set()

    @property
    def paused(self) -> bool:
        return self._pause_event.is_set()

    # -- Thread-Lebenszyklus -------------------------------------------
    def run(self) -> None:
        log.info("Tracker gestartet (Intervall %ss)", self.config.get("poll_interval_seconds"))
        self._maybe_purge()
        interval = max(1, int(self.config.get("poll_interval_seconds", 3)))
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception:  # noqa: BLE001  – Loop darf nie sterben
                log.exception("Fehler im Tracker-Tick")
            self._stop_event.wait(interval)
        self._close_current(time.time())
        try:
            self.db.close()
        except Exception:  # noqa: BLE001
            pass
        log.info("Tracker gestoppt")

    # -- Kernlogik ----------------------------------------------------
    def _tick(self) -> None:
        now = time.time()
        now_dt = datetime.now()
        today = now_dt.strftime("%Y-%m-%d")

        self._maybe_purge(today)
        self._emit_status()

        # Mitternachts-Split: offenes Segment am Tageswechsel abschneiden.
        if self._seg and self._seg["day"] != today:
            self._close_current(_midnight_epoch(now_dt))

        if self._pause_event.is_set():
            self._close_current(now)
            return

        idle = winapi.get_idle_seconds()
        threshold = float(self.config.get("idle_threshold_seconds", 120))

        if winapi.is_workstation_locked():
            self._transition(STATE_LOCKED, now, idle, today, info=None)
        elif idle >= threshold:
            self._transition(STATE_IDLE, now, idle, today, info=None)
        else:
            self._transition(STATE_ACTIVE, now, idle, today, info=winapi.get_active_window() or {})

    def _transition(self, state: str, now: float, idle: float, today: str, info: dict | None) -> None:
        info = info or {}
        process = info.get("process", "")
        raw_title = info.get("title", "")
        title = raw_title if self.config.get("track_titles", True) else ""
        exe_path = info.get("exe_path", "")

        if state == STATE_ACTIVE:
            if is_private(process, raw_title, self.config):
                app, document, category = "Privat", "", "Privat"
                title, exe_path = "", ""
                process = process or "privat"
            else:
                app = friendly_app_name(process, self.config) if process else "Unbekannt"
                document = parse_document(title, process)
                category = categorize(process, title, self.config)
            key = (state, process.lower(), title)
        else:
            app = "Abwesend" if state == STATE_IDLE else "Gesperrt"
            document, category, process, exe_path, title = "", "Abwesenheit", "", "", ""
            key = (state,)

        cur = self._seg
        if cur and cur["key"] == key:
            self.db.touch_segment(cur["id"], now)
            cur["end"] = now
            return

        # Statuswechsel – Grenze ggf. auf den echten Ereigniszeitpunkt zurückdatieren.
        boundary = now
        if cur:
            prev = cur["state"]
            crossing_idle = (
                (prev == STATE_ACTIVE and state in (STATE_IDLE, STATE_LOCKED))
                or (prev in (STATE_IDLE, STATE_LOCKED) and state == STATE_ACTIVE)
            )
            if crossing_idle:
                boundary = min(now, max(cur["start"], now - idle))
            self._close_current(boundary)

        seg_id = self.db.open_segment(
            start_utc=boundary, day=today, state=state, process=process,
            exe_path=exe_path, app=app, title=title, document=document, category=category,
        )
        self._seg = {"id": seg_id, "key": key, "state": state, "day": today,
                     "start": boundary, "end": boundary}

    def _close_current(self, end_utc: float) -> None:
        cur = self._seg
        if not cur:
            return
        end_utc = max(end_utc, cur["start"])
        self.db.touch_segment(cur["id"], end_utc)
        # Sehr kurze Segmente (Klick-durch) verwerfen.
        if end_utc - cur["start"] < float(self.config.get("min_segment_seconds", 1)):
            self.db.delete_segment(cur["id"])
        self._seg = None

    # -- Nebenaufgaben ----------------------------------------------
    def _maybe_purge(self, today: str | None = None) -> None:
        today = today or datetime.now().strftime("%Y-%m-%d")
        if self._last_purge == today:
            return
        self._last_purge = today
        try:
            removed = self.db.purge_older_than(int(self.config.get("retention_days", 90)))
            if removed:
                log.info("Aufräumen: %s alte Segmente gelöscht", removed)
        except Exception:  # noqa: BLE001
            log.exception("Purge fehlgeschlagen")

    def _emit_status(self, force: bool = False) -> None:
        if not self.status_callback:
            return
        now = time.time()
        if not force and now - self._last_status < 30:
            return
        self._last_status = now
        try:
            active_today = self.db.active_seconds_between(_midnight_epoch(datetime.now()), now + 1)
            self.status_callback(active_today, self._pause_event.is_set())
        except Exception:  # noqa: BLE001
            log.exception("status_callback fehlgeschlagen")
