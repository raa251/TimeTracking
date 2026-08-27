"""Kommandozeilen-Einstieg.

    python -m timetracker                 Tray-App starten (Standard)
    python -m timetracker dashboard       nur das Dashboard öffnen
    python -m timetracker report [-d 7]   Klartext-Bericht ausgeben
    python -m timetracker report --day 2026-08-27
    python -m timetracker export --format csv --out bericht.csv [-d 7]
    python -m timetracker autostart --enable | --disable | --status
    python -m timetracker status          kurze Zusammenfassung "heute"
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from . import __version__
from .app import main as run_tray, setup_logging
from .config import DB_PATH, Config
from .database import Database


def _report(args) -> int:
    db = Database(DB_PATH)
    config = Config()
    from .reporting import text_report
    print(text_report(db, config, days=args.days, single_day=args.day))
    return 0


def _export(args) -> int:
    from . import reporting
    db = Database(DB_PATH)
    config = Config()
    if args.day:
        segments = reporting.load_day(db, args.day)
    else:
        days = reporting.last_n_days(args.days)
        segments = reporting.load_range(db, days[0], days[-1])
    if not segments:
        print("Keine Daten für den gewählten Zeitraum.", file=sys.stderr)
        return 1
    content = (reporting.export_csv(segments) if args.format == "csv"
               else reporting.export_json(segments, config))
    if args.out:
        encoding = "utf-8-sig" if args.format == "csv" else "utf-8"
        with open(args.out, "w", encoding=encoding, newline="") as fh:
            fh.write(content)
        print(f"Gespeichert: {args.out}")
    else:
        sys.stdout.write(content)
    return 0


def _autostart(args) -> int:
    from . import autostart
    if args.enable:
        autostart.enable()
    elif args.disable:
        autostart.disable()
    print("Autostart:", "aktiv" if autostart.is_enabled() else "inaktiv")
    return 0


def _status(_args) -> int:
    from .reporting import fmt_duration, load_day, summarize
    db = Database(DB_PATH)
    today = datetime.now().strftime("%Y-%m-%d")
    s = summarize(load_day(db, today), Config())
    print(f"Heute ({today})")
    print(f"  aktiv    : {fmt_duration(s['total_active'])}")
    print(f"  abwesend : {fmt_duration(s['total_idle'])}")
    if s["top_app"]:
        print(f"  Top-App  : {s['top_app']['label']} ({fmt_duration(s['top_app']['seconds'], short=True)})")
    return 0


def _dashboard(_args) -> int:
    from .dashboard import open_dashboard
    open_dashboard(Database(DB_PATH), Config())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="timetracker", description="Automatische Zeiterfassung (aktives Fenster).")
    p.add_argument("--version", action="version", version=f"TimeTracker {__version__}")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("run", help="Tray-App starten (Standard)")
    sub.add_parser("dashboard", help="nur das Dashboard-Fenster öffnen")
    sub.add_parser("status", help="kurze Zusammenfassung für heute")

    rep = sub.add_parser("report", help="Klartext-Bericht ausgeben")
    rep.add_argument("-d", "--days", type=int, default=7)
    rep.add_argument("--day", help="einzelnes Datum YYYY-MM-DD")

    exp = sub.add_parser("export", help="Segmente als CSV/JSON exportieren")
    exp.add_argument("--format", choices=["csv", "json"], default="csv")
    exp.add_argument("--out", help="Zieldatei (sonst stdout)")
    exp.add_argument("-d", "--days", type=int, default=7)
    exp.add_argument("--day", help="einzelnes Datum YYYY-MM-DD")

    auto = sub.add_parser("autostart", help="Windows-Autostart verwalten")
    auto.add_argument("--enable", action="store_true")
    auto.add_argument("--disable", action="store_true")
    auto.add_argument("--status", action="store_true")

    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    setup_logging()
    dispatch = {
        "report": _report,
        "export": _export,
        "autostart": _autostart,
        "status": _status,
        "dashboard": _dashboard,
    }
    if args.command in dispatch:
        return dispatch[args.command](args)
    return run_tray()


if __name__ == "__main__":
    raise SystemExit(main())
