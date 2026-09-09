"""SQLite-Speicher für die erfassten Aktivitäts-Segmente.

Ein *Segment* ist ein zusammenhängender Zeitraum, in dem sich weder aktives
Fenster noch Status (aktiv/abwesend/gesperrt) geändert haben. Solange ein
Segment "offen" ist, wird bei jedem Tick nur ``end_utc`` aktualisiert – ein
Absturz kostet daher höchstens ein Poll-Intervall an Daten.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS segments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    start_utc   REAL    NOT NULL,
    end_utc     REAL    NOT NULL,
    day         TEXT    NOT NULL,          -- lokales Datum 'YYYY-MM-DD' (Start)
    state       TEXT    NOT NULL,          -- 'active' | 'idle' | 'locked'
    process     TEXT    NOT NULL DEFAULT '',
    exe_path    TEXT    NOT NULL DEFAULT '',
    app         TEXT    NOT NULL DEFAULT '',
    title       TEXT    NOT NULL DEFAULT '',
    document    TEXT    NOT NULL DEFAULT '',
    category    TEXT    NOT NULL DEFAULT '',
    branch      TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_segments_day   ON segments(day);
CREATE INDEX IF NOT EXISTS idx_segments_start ON segments(start_utc);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._local = threading.local()
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Fehlende Spalten in bestehenden Datenbanken ergänzen."""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(segments)")}
        if "branch" not in cols:
            conn.execute("ALTER TABLE segments ADD COLUMN branch TEXT NOT NULL DEFAULT ''")

    # -- Verbindungshandling (eine Connection pro Thread) -------------------
    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -- Schreiboperationen (nur aus dem Tracker-Thread) -------------------
    def open_segment(
        self,
        start_utc: float,
        day: str,
        state: str,
        process: str = "",
        exe_path: str = "",
        app: str = "",
        title: str = "",
        document: str = "",
        category: str = "",
        branch: str = "",
    ) -> int:
        cur = self._connect().execute(
            """INSERT INTO segments
               (start_utc, end_utc, day, state, process, exe_path, app, title, document, category, branch)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (start_utc, start_utc, day, state, process, exe_path, app, title, document, category, branch),
        )
        return int(cur.lastrowid)

    def touch_segment(self, seg_id: int, end_utc: float) -> None:
        self._connect().execute(
            "UPDATE segments SET end_utc = ? WHERE id = ?", (end_utc, seg_id)
        )

    def delete_segment(self, seg_id: int) -> None:
        self._connect().execute("DELETE FROM segments WHERE id = ?", (seg_id,))

    def purge_older_than(self, days: int) -> int:
        cutoff = (datetime.now() - timedelta(days=max(7, days))).strftime("%Y-%m-%d")
        cur = self._connect().execute("DELETE FROM segments WHERE day < ?", (cutoff,))
        return cur.rowcount

    def set_meta(self, key: str, value: str) -> None:
        self._connect().execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._connect().execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    # -- Leseoperationen --------------------------------------------------
    def segments_between(self, start_day: str, end_day: str) -> list[sqlite3.Row]:
        return self._connect().execute(
            "SELECT * FROM segments WHERE day >= ? AND day <= ? ORDER BY start_utc",
            (start_day, end_day),
        ).fetchall()

    def segments_for_day(self, day: str) -> list[sqlite3.Row]:
        return self._connect().execute(
            "SELECT * FROM segments WHERE day = ? ORDER BY start_utc", (day,)
        ).fetchall()

    def active_seconds_between(self, start_utc: float, end_utc: float) -> float:
        row = self._connect().execute(
            """SELECT COALESCE(SUM(end_utc - start_utc), 0) AS s
               FROM segments
               WHERE state = 'active' AND start_utc >= ? AND start_utc < ?""",
            (start_utc, end_utc),
        ).fetchone()
        return float(row["s"])

    def days_with_data(self) -> set[str]:
        rows = self._connect().execute("SELECT DISTINCT day FROM segments").fetchall()
        return {r["day"] for r in rows}

    def first_last_day(self) -> tuple[str | None, str | None]:
        row = self._connect().execute(
            "SELECT MIN(day) AS lo, MAX(day) AS hi FROM segments"
        ).fetchone()
        return (row["lo"], row["hi"])

    def row_count(self) -> int:
        return int(self._connect().execute("SELECT COUNT(*) AS c FROM segments").fetchone()["c"])
