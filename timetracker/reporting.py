"""Aggregation der Segmente zu Tages-/Wochenberichten."""
from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from copy import copy
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

from . import classify
from .config import Config
from .database import Database


@dataclass
class Segment:
    id: int
    start_utc: float
    end_utc: float
    day: str
    state: str
    process: str
    exe_path: str
    app: str
    title: str
    document: str
    category: str
    branch: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end_utc - self.start_utc)

    @property
    def start_dt(self) -> datetime:
        return datetime.fromtimestamp(self.start_utc)

    @property
    def end_dt(self) -> datetime:
        return datetime.fromtimestamp(self.end_utc)


def _rows_to_segments(rows) -> list[Segment]:
    fields = Segment.__dataclass_fields__
    out = []
    for r in rows:
        keys = r.keys()
        out.append(Segment(**{k: r[k] for k in fields if k in keys}))
    return out


def collapse_projects(segments: list[Segment], config: Config) -> list[Segment]:
    """Fasst aufeinanderfolgende Editor-Segmente desselben Projekts (+ Branch) zusammen.

    Für die Standardansicht: statt „datei_a.py, datei_b.py, …“ nur der Projektname.
    Nicht-Editor-Segmente bleiben unverändert.
    """
    out: list[Segment] = []
    prev_key = None
    for s in segments:
        editor = s.state == "active" and classify.is_code_editor(s.process, config)
        if editor:
            if "/" in s.document:                       # neues Format "Projekt/pfad/datei"
                project = s.document.split("/", 1)[0].strip()
            else:                                        # nur Dateiname -> Projekt aus dem Titel
                project = classify.project_name(s.title, s.process) or s.document
            key = (s.app, project, s.branch, s.day)
        else:
            key = None

        if (key is not None and key == prev_key and out
                and s.start_utc - out[-1].end_utc <= 2.0):
            out[-1].end_utc = s.end_utc
        else:
            seg = copy(s)
            if editor:
                seg.document = project
                seg.title = project + (f" [{s.branch}]" if s.branch else "")
            out.append(seg)
        prev_key = key
    return out


def last_n_days(n: int) -> list[str]:
    today = datetime.now().date()
    return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n - 1, -1, -1)]


def load_day(db: Database, day: str) -> list[Segment]:
    return _rows_to_segments(db.segments_for_day(day))


def load_range(db: Database, start_day: str, end_day: str) -> list[Segment]:
    return _rows_to_segments(db.segments_between(start_day, end_day))


def fmt_duration(seconds: float, short: bool = False) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if short:
        if h:
            return f"{h}h {m:02d}m"
        if m:
            return f"{m}m {s:02d}s"
        return f"{s}s"
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _pct(part: float, whole: float) -> float:
    return (part / whole * 100.0) if whole else 0.0


def summarize(segments: list[Segment], config: Config | None = None) -> dict:
    """Kennzahlen + Ranglisten über eine Segmentliste (Tag oder Zeitraum)."""
    active = [s for s in segments if s.state == "active"]
    idle = [s for s in segments if s.state == "idle"]
    locked = [s for s in segments if s.state == "locked"]

    total_active = sum(s.duration for s in active)
    total_idle = sum(s.duration for s in idle)
    total_locked = sum(s.duration for s in locked)

    by_app: dict[str, float] = defaultdict(float)
    by_category: dict[str, float] = defaultdict(float)
    by_document: dict[tuple[str, str, str], float] = defaultdict(float)
    doc_category: dict[tuple[str, str, str], str] = {}
    by_day: dict[str, dict[str, float]] = defaultdict(lambda: {"active": 0.0, "idle": 0.0, "locked": 0.0})

    for s in segments:
        by_day[s.day][s.state] = by_day[s.day].get(s.state, 0.0) + s.duration
    for s in active:
        by_app[s.app or s.process or "Unbekannt"] += s.duration
        by_category[s.category or "Sonstiges"] += s.duration
        if s.document:
            dk = (s.app, s.document, s.branch)
            by_document[dk] += s.duration
            doc_category.setdefault(dk, s.category or "Sonstiges")

    def rank(d: dict, key_fmt=lambda k: k):
        items = sorted(d.items(), key=lambda kv: kv[1], reverse=True)
        return [
            {"label": key_fmt(k), "seconds": v, "pct": _pct(v, total_active)}
            for k, v in items
        ]

    # längster ununterbrochener Fokus auf dieselbe App
    longest_focus = {"app": None, "seconds": 0.0}
    run_app, run_len = None, 0.0
    switches = 0
    for s in active:
        if s.app == run_app:
            run_len += s.duration
        else:
            if run_app is not None:
                switches += 1
            run_app, run_len = s.app, s.duration
        if run_len > longest_focus["seconds"]:
            longest_focus = {"app": run_app, "seconds": run_len}

    # Produktivitäts-Score
    prod_seconds = {"produktiv": 0.0, "neutral": 0.0, "ablenkend": 0.0}
    if config is not None:
        weights = config.productivity
        for cat, secs in by_category.items():
            w = weights.get(cat, 0)
            bucket = "produktiv" if w > 0 else "ablenkend" if w < 0 else "neutral"
            prod_seconds[bucket] += secs

    first = min((s.start_dt for s in active), default=None)
    last = max((s.end_dt for s in active), default=None)

    return {
        "total_active": total_active,
        "total_idle": total_idle,
        "total_locked": total_locked,
        "total_tracked": total_active + total_idle + total_locked,
        "by_app": rank(by_app),
        "by_category": rank(by_category),
        "by_document": [
            {"app": a, "document": d, "branch": b, "category": doc_category.get((a, d, b), ""),
             "seconds": v, "pct": _pct(v, total_active)}
            for (a, d, b), v in sorted(by_document.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "by_day": dict(by_day),
        "longest_focus": longest_focus,
        "switches": switches,
        "top_app": (rank(by_app)[0] if by_app else None),
        "top_category": (rank(by_category)[0] if by_category else None),
        "first_activity": first,
        "last_activity": last,
        "productivity": prod_seconds,
        "segment_count": len(segments),
    }


def hourly_active(segments: list[Segment]) -> list[float]:
    """Aktive Sekunden je Stunde (0..23) – für den Tages-Heatmap/Barchart."""
    buckets = [0.0] * 24
    for s in segments:
        if s.state != "active":
            continue
        start, end = s.start_dt, s.end_dt
        cursor = start
        while cursor < end:
            hour_end = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            chunk_end = min(end, hour_end)
            buckets[cursor.hour] += (chunk_end - cursor).total_seconds()
            cursor = chunk_end
    return buckets


def timeline(segments: list[Segment], include_states=("active", "idle", "locked")) -> list[dict]:
    """Chronologisches Log: von–bis, Dauer, App, Fenster/Datei, Kategorie, Status."""
    out = []
    labels = {"active": "aktiv", "idle": "abwesend", "locked": "gesperrt"}
    for s in segments:
        if s.state not in include_states:
            continue
        out.append(
            {
                "date": s.start_dt.strftime("%d.%m.%Y"),
                "start": s.start_dt.strftime("%H:%M"),
                "end": s.end_dt.strftime("%H:%M"),
                "start_iso": s.start_dt.isoformat(timespec="seconds"),
                "end_iso": s.end_dt.isoformat(timespec="seconds"),
                "duration": s.duration,
                "duration_h": fmt_duration(s.duration, short=True),
                "app": s.app,
                "window": s.document or s.title,
                "title": s.title,
                "branch": s.branch,
                "category": s.category,
                "state": labels.get(s.state, s.state),
            }
        )
    return out


# -- Export --------------------------------------------------------------
def export_csv(segments: list[Segment]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        ["Datum", "Von", "Bis", "Dauer (s)", "Dauer", "Status", "App", "Prozess",
         "Fenster/Datei", "Branch", "Fenstertitel", "Kategorie"]
    )
    for s in segments:
        writer.writerow(
            [
                s.day,
                s.start_dt.strftime("%H:%M:%S"),
                s.end_dt.strftime("%H:%M:%S"),
                f"{s.duration:.0f}",
                fmt_duration(s.duration, short=True),
                s.state,
                s.app,
                s.process,
                s.document,
                s.branch,
                s.title,
                s.category,
            ]
        )
    return buf.getvalue()


def export_json(segments: list[Segment], config: Config | None = None) -> str:
    days = sorted({s.day for s in segments})
    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "days": days,
        "summary": _json_safe(summarize(segments, config)),
        "segments": [
            {
                **{k: v for k, v in asdict(s).items()},
                "duration": s.duration,
                "start_iso": s.start_dt.isoformat(timespec="seconds"),
                "end_iso": s.end_dt.isoformat(timespec="seconds"),
            }
            for s in segments
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat(timespec="seconds")
    return obj


def text_report(db: Database, config: Config, days: int = 7, single_day: str | None = None) -> str:
    """Kompakter Klartext-Bericht für die Kommandozeile."""
    if single_day:
        segs = load_day(db, single_day)
        header = f"Bericht für {single_day}"
        day_list = [single_day]
    else:
        day_list = last_n_days(days)
        segs = load_range(db, day_list[0], day_list[-1])
        header = f"Bericht {day_list[0]} bis {day_list[-1]} ({days} Tage)"

    s = summarize(segs, config)
    lines = [header, "=" * len(header), ""]
    lines.append(f"Aktive Zeit gesamt : {fmt_duration(s['total_active'])}")
    lines.append(f"Abwesend (idle)    : {fmt_duration(s['total_idle'])}")
    lines.append(f"Gesperrt           : {fmt_duration(s['total_locked'])}")
    if s["first_activity"]:
        lines.append(f"Erste Aktivität    : {s['first_activity']:%Y-%m-%d %H:%M}")
        lines.append(f"Letzte Aktivität   : {s['last_activity']:%Y-%m-%d %H:%M}")
    lines.append(f"App-Wechsel        : {s['switches']}")
    if s["longest_focus"]["app"]:
        lines.append(
            f"Längster Fokus     : {s['longest_focus']['app']} "
            f"({fmt_duration(s['longest_focus']['seconds'], short=True)})"
        )
    lines.append("")

    if len(day_list) > 1:
        lines.append("Pro Tag:")
        for day in day_list:
            d = s["by_day"].get(day, {})
            lines.append(f"  {day}  aktiv {fmt_duration(d.get('active', 0.0), short=True):>10}")
        lines.append("")

    lines.append("Top-Apps:")
    for row in s["by_app"][:15]:
        lines.append(f"  {row['label'][:38]:<38} {fmt_duration(row['seconds'], short=True):>10}  {row['pct']:5.1f}%")
    lines.append("")
    lines.append("Kategorien:")
    for row in s["by_category"]:
        lines.append(f"  {row['label'][:38]:<38} {fmt_duration(row['seconds'], short=True):>10}  {row['pct']:5.1f}%")

    if single_day:
        lines.append("")
        lines.append("Verlauf:")
        for e in timeline(segs):
            lines.append(
                f"  {e['start']}–{e['end']}  {e['duration_h']:>9}  "
                f"{e['app'][:22]:<22}  {(e['window'] or '')[:40]}"
            )
    return "\n".join(lines)
