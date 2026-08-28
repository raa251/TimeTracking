"""Der Hintergrund-Thread, der das aktive Fenster pollt und Segmente schreibt."""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, time as dtime

from . import gitinfo, winapi
from .classify import (
    categorize,
    editor_document,
    friendly_app_name,
    is_code_editor,
    is_ignored,
    is_private,
    parse_document,
    path_from_title,
    project_name,
)
from .config import Config
from .database import Database

log = logging.getLogger(__name__)

STATE_ACTIVE = "active"
STATE_IDLE = "idle"
STATE_LOCKED = "locked"


def _midnight_epoch(dt: datetime) -> float:
    return datetime.combine(dt.date(), dtime.min).timestamp()


def _looks_like_filename(text: str) -> bool:
    """Sieht wie ein einzelner Dateiname aus (kein Pfad, mit Endung)?"""
    return bool(text) and "/" not in text and "\\" not in text and "." in text[1:] and len(text) < 120


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

        self._own_pid = os.getpid()            # eigene Fenster nur als "1 Fenster" werten
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._seg: dict | None = None          # aktuell offenes Segment
        self._last_purge = ""
        self._last_status = 0.0
        self._repo_map: dict[str, str] = {}    # ordnername -> repo-pfad (Hintergrund-Scan)
        self._repo_lock = threading.Lock()
        self._branch_cache: dict[str, tuple[str, float]] = {}       # repo -> (branch, geprüft_um)
        self._path_repo_cache: dict[str, tuple[str, str, float]] = {}  # ordner -> (repo, branch, um)
        self._file_repo_cache: dict[str, tuple[str, str, float]] = {}  # datei -> (repo, rel, um)
        self._last_repo_scan = 0.0

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

    # -- Git-Repos im Hintergrund suchen -----------------------------
    def _scan_repos(self) -> None:
        try:
            repos = gitinfo.discover_repos(self.config.get("project_roots", []))
            with self._repo_lock:
                self._repo_map = repos
        except Exception:  # noqa: BLE001
            log.exception("Repo-Scan fehlgeschlagen")

    # -- Thread-Lebenszyklus -------------------------------------------
    def run(self) -> None:
        log.info("Tracker gestartet (Intervall %ss)", self.config.get("poll_interval_seconds"))
        self._maybe_purge()
        threading.Thread(target=self._scan_repos, name="RepoScan", daemon=True).start()
        self._last_repo_scan = time.time()
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception:  # noqa: BLE001  – Loop darf nie sterben
                log.exception("Fehler im Tracker-Tick")
            if time.time() - self._last_repo_scan > 900:  # alle 15 min neue Repos suchen
                self._last_repo_scan = time.time()
                threading.Thread(target=self._scan_repos, name="RepoScan", daemon=True).start()
            # Intervall bei jedem Durchlauf neu lesen – Änderung wirkt ohne Neustart
            self._stop_event.wait(max(1, int(self.config.get("poll_interval_seconds", 3))))
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
            info = winapi.get_active_window() or {}
            if info.get("process") and is_ignored(info["process"], info.get("title", ""), self.config):
                # transientes Shell-Fenster – laufenden Eintrag einfach weiterlaufen lassen
                if self._seg and self._seg["state"] == STATE_ACTIVE:
                    self.db.touch_segment(self._seg["id"], now)
                    self._seg["end"] = now
                return
            self._transition(STATE_ACTIVE, now, idle, today, info=info)

    def _transition(self, state: str, now: float, idle: float, today: str, info: dict | None) -> None:
        info = info or {}
        process = info.get("process", "")
        raw_title = info.get("title", "")
        title = raw_title if self.config.get("track_titles", True) else ""
        exe_path = info.get("exe_path", "")

        document = branch = ""
        # Es wird pro Datei/Tab gespeichert; das Zusammenfassen zu "Projekt"
        # passiert erst bei der Anzeige (Detailansicht-Schalter im Dashboard).
        if state == STATE_ACTIVE:
            if info.get("pid") and info["pid"] == self._own_pid:
                # TimeTracker selbst (Dashboard, Einstellungen, Farb-/Kategorie-Fenster …)
                # -> alle als EIN Fenster werten, nicht pro Dialog aufsplitten.
                app, process = "TimeTracker", "timetracker.exe"
                title = document = branch = ""
                category = (self.config.data.get("app_categories", {}).get(app)
                            or categorize("timetracker.exe", "", self.config))
                key = (state, "timetracker.exe", "")
            elif is_private(process, raw_title, self.config):
                app, document, category = "Privat", "", "Privat"
                title, exe_path = "", ""
                process = process or "privat"
                key = (state, process.lower(), title)
            else:
                app = friendly_app_name(process, self.config) if process else "Unbekannt"
                category = (self.config.data.get("app_categories", {}).get(app)
                            or categorize(process, title, self.config))
                editor = is_code_editor(process, self.config)
                if editor:
                    document = editor_document(title, process)
                    project_hint = project_name(title, process)
                else:
                    document = parse_document(title, process)
                    project_hint = document if process.lower() == "explorer.exe" else ""
                document, branch = self._git_context(raw_title, project_hint, document, editor)
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
            exe_path=exe_path, app=app, title=title, document=document,
            category=category, branch=branch,
        )
        self._seg = {"id": seg_id, "key": key, "state": state, "day": today,
                     "start": boundary, "end": boundary}

    def _head_cached(self, repo_dir: str) -> str:
        now = time.time()
        cached = self._branch_cache.get(repo_dir)
        if cached and now - cached[1] < 15:
            return cached[0]
        branch = gitinfo.head_branch(repo_dir)
        self._branch_cache[repo_dir] = (branch, now)
        return branch

    def _git_context(self, raw_title: str, project_hint: str, doc_from_title: str,
                     editor: bool) -> tuple[str, str]:
        """Ermittelt (document, branch) über den echten Dateipfad bzw. den Ordnernamen.

        Der Branch kommt ausschließlich aus ``.git/HEAD`` – nie aus dem Fenstertitel.
        """
        repo_dir = branch = ""

        # 1. Voller Dateipfad im Titel (MetaEditor, Notepad++, …) -> .git aufwärts suchen
        abs_path = path_from_title(raw_title)
        if abs_path:
            now = time.time()
            folder = os.path.dirname(abs_path)
            cached = self._path_repo_cache.get(folder)
            if cached and now - cached[2] < 30:
                repo_dir, branch = cached[0], cached[1]
            else:
                repo_dir, branch = gitinfo.repo_context(abs_path)
                self._path_repo_cache[folder] = (repo_dir, branch, now)

        # 2. Sonst über den Ordner-/Projektnamen aus dem gescannten Repo-Verzeichnis
        if not repo_dir and project_hint:
            with self._repo_lock:
                repo_dir = self._repo_map.get(project_hint.strip().lower(), "")
            if repo_dir:
                branch = self._head_cached(repo_dir)

        if repo_dir and abs_path:
            proj = os.path.basename(repo_dir.rstrip("\\/"))
            try:
                rel = os.path.relpath(abs_path, repo_dir).replace("\\", "/")
            except ValueError:
                rel = os.path.basename(abs_path)
            return f"{proj}/{rel}", branch
        if abs_path and not repo_dir:
            # Pfad ohne Repo -> auf die letzten zwei Komponenten kürzen
            comps = [c for c in abs_path.replace("\\", "/").split("/") if c]
            return ("/".join(comps[-2:]) if len(comps) >= 2 else doc_from_title), ""

        # 3. Editor ohne Projekt/Pfad im Titel (MetaEditor): Datei in den Repos suchen
        if not repo_dir and editor and _looks_like_filename(doc_from_title):
            repo_dir, rel = self._find_file_repo(doc_from_title)
            if repo_dir:
                proj = os.path.basename(repo_dir.rstrip("\\/"))
                return f"{proj}/{rel}", self._head_cached(repo_dir)

        if repo_dir and not editor:
            # z. B. Explorer in einem Repo: Projektname statt bloßem Ordnernamen
            return os.path.basename(repo_dir.rstrip("\\/")), branch
        return doc_from_title, branch

    def _find_file_repo(self, filename: str) -> tuple[str, str]:
        """(repo_dir, repo-relativer-pfad) für eine Datei, eindeutig in genau einem Repo."""
        key = filename.strip().lower()
        now = time.time()
        cached = self._file_repo_cache.get(key)
        if cached and now - cached[2] < 120:
            return cached[0], cached[1]
        with self._repo_lock:
            repos = list(self._repo_map.values())
        hits = gitinfo.find_file_in_repos(filename, repos)
        repo_dir, rel = hits[0] if len(hits) == 1 else ("", "")
        self._file_repo_cache[key] = (repo_dir, rel, now)
        return repo_dir, rel

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
