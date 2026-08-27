"""Tkinter-Dashboard: Kennzahlen, Diagramme, App-Ranglisten und das Verlaufs-Log."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox

import tkinter as tk
from tkinter import ttk

from . import reporting
from .config import EXPORT_DIR, DATA_DIR, Config
from .database import Database
from .reporting import fmt_duration

log = logging.getLogger(__name__)

# Farben pro Kategorie (für Balken & Tabellen-Markierung)
CATEGORY_COLORS = {
    "Entwicklung": "#2563eb",
    "Browser / Recherche": "#0891b2",
    "Kommunikation": "#7c3aed",
    "Office / Dokumente": "#16a34a",
    "Design / Kreativ": "#db2777",
    "Medien": "#ea580c",
    "Gaming": "#dc2626",
    "System / Datei": "#64748b",
    "Sonstiges": "#94a3b8",
    "Abwesenheit": "#cbd5e1",
    "Privat": "#334155",
}
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _cat_color(name: str) -> str:
    return CATEGORY_COLORS.get(name, "#94a3b8")


class Dashboard:
    def __init__(self, db: Database, config: Config, shutdown_event: threading.Event | None = None):
        self.db = db
        self.config = config
        self.shutdown_event = shutdown_event
        self._after_jobs: list[str] = []

        self.root = tk.Tk()
        self.root.title("TimeTracker – Dashboard")
        self.root.geometry("1060x740")
        self.root.minsize(900, 600)

        self.range_days = reporting.last_n_days(7)
        self.selection = tk.StringVar(value="week")

        self._build_style()
        self._build_toolbar()
        self._build_cards()
        self._build_notebook()
        self._build_statusbar()

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._refresh()
        self._schedule(30_000, self._auto_refresh)
        self._watch_shutdown()

    # -- Aufbau ---------------------------------------------------------
    def _build_style(self) -> None:
        import tkinter.font as tkfont

        style = ttk.Style(self.root)
        for theme in ("vista", "winnative", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        row_h = tkfont.Font(family="Segoe UI", size=9).metrics("linespace") + 10
        style.configure("Card.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("CardValue.TLabel", font=("Segoe UI Semibold", 13), background="#ffffff")
        style.configure("CardCaption.TLabel", font=("Segoe UI", 8), foreground="#64748b", background="#ffffff")
        style.configure("Treeview", rowheight=row_h, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9))
        style.configure("TNotebook.Tab", padding=(14, 6))

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, padding=(10, 8))
        bar.pack(fill="x")

        ttk.Label(bar, text="Zeitraum:").pack(side="left", padx=(0, 6))

        self._period_labels = ["Letzte 7 Tage"]
        self._period_values = ["week"]
        for day in self.range_days:
            d = datetime.strptime(day, "%Y-%m-%d")
            self._period_labels.append(f"{WEEKDAYS[d.weekday()]}  {d.strftime('%d.%m.%Y')}")
            self._period_values.append(day)

        self.period_box = ttk.Combobox(
            bar, values=self._period_labels, state="readonly", width=22,
            font=("Segoe UI", 9),
        )
        self.period_box.current(0)
        self.period_box.bind("<<ComboboxSelected>>", self._on_period_change)
        self.period_box.pack(side="left")

        ttk.Button(bar, text="Ordner", width=8, command=self._open_folder).pack(side="right")
        ttk.Button(bar, text="Export JSON", command=lambda: self._export("json")).pack(side="right", padx=4)
        ttk.Button(bar, text="Export CSV", command=lambda: self._export("csv")).pack(side="right")
        ttk.Button(bar, text="Aktualisieren", command=self._refresh).pack(side="right", padx=8)

    def _on_period_change(self, _event=None) -> None:
        idx = self.period_box.current()
        self.selection.set(self._period_values[max(0, idx)])
        self._refresh()

    def _build_cards(self) -> None:
        self.cards_frame = ttk.Frame(self.root, padding=(10, 2))
        self.cards_frame.pack(fill="x")
        self._cards: dict[str, ttk.Label] = {}
        specs = [
            ("active", "Aktive Zeit"),
            ("idle", "Abwesend"),
            ("locked", "Gesperrt"),
            ("span", "Zeitfenster"),
            ("switches", "App-Wechsel"),
            ("focus", "Längster Fokus"),
            ("goal", "Tagesziel"),
        ]
        for i, (key, caption) in enumerate(specs):
            card = ttk.Frame(self.cards_frame, style="Card.TFrame", padding=(9, 6))
            card.grid(row=0, column=i, sticky="nsew", padx=3, pady=4)
            self.cards_frame.columnconfigure(i, weight=1, uniform="cards")
            value = ttk.Label(card, text="–", style="CardValue.TLabel")
            value.pack(anchor="w")
            ttk.Label(card, text=caption, style="CardCaption.TLabel").pack(anchor="w")
            self._cards[key] = value

    def _build_notebook(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=(4, 6))

        # -- Tab: Übersicht -------------------------------------------
        tab_overview = ttk.Frame(nb, padding=8)
        nb.add(tab_overview, text="  Übersicht  ")
        self.chart = tk.Canvas(tab_overview, height=270, bg="#ffffff", highlightthickness=1,
                               highlightbackground="#e2e8f0")
        self.chart.pack(fill="x")
        self.chart.bind("<Configure>", lambda e: self._draw_chart())
        cat_wrap = ttk.LabelFrame(tab_overview, text="Kategorien  ·  Verteilung der aktiven Zeit", padding=6)
        cat_wrap.pack(fill="both", expand=True, pady=(8, 0))
        self.cat_tree = self._make_tree(cat_wrap, ("Kategorie", "Dauer", "Anteil"),
                                        widths=(360, 130, 100), stretch_col="Kategorie")

        # -- Tab: Apps ----------------------------------------------
        tab_apps = ttk.Frame(nb, padding=8)
        nb.add(tab_apps, text="  Apps  ")
        self.app_tree = self._make_tree(tab_apps, ("App", "Kategorie", "Dauer", "Anteil"),
                                        widths=(300, 260, 120, 100), stretch_col="Kategorie")

        # -- Tab: Verlauf -----------------------------------------
        tab_log = ttk.Frame(nb, padding=8)
        nb.add(tab_log, text="  Verlauf (Log)  ")
        self.log_filter = tk.StringVar(value="alle")
        fbar = ttk.Frame(tab_log)
        fbar.pack(fill="x", pady=(0, 4))
        ttk.Label(fbar, text="Anzeigen:").pack(side="left")
        for lbl in ("alle", "nur aktiv"):
            ttk.Radiobutton(fbar, text=lbl, value=lbl, variable=self.log_filter,
                            command=self._refresh).pack(side="left", padx=4)
        self.log_tree = self._make_tree(
            tab_log, ("Von", "Bis", "Dauer", "App", "Fenster / Datei", "Kategorie", "Status"),
            widths=(88, 88, 96, 200, 340, 200, 78), stretch_col="Fenster / Datei",
        )

        # -- Tab: Dateien -----------------------------------------
        tab_docs = ttk.Frame(nb, padding=8)
        nb.add(tab_docs, text="  Dateien / Fenster  ")
        self.doc_tree = self._make_tree(tab_docs, ("App", "Fenster / Datei", "Dauer", "Anteil"),
                                        widths=(240, 520, 120, 100), stretch_col="Fenster / Datei")

    def _build_statusbar(self) -> None:
        self.status = ttk.Label(self.root, text="", anchor="w", padding=(10, 3),
                                font=("Segoe UI", 8), foreground="#64748b")
        self.status.pack(fill="x")

    def _make_tree(self, parent, columns, widths, stretch_col: str | None = None) -> ttk.Treeview:
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True)
        tree = ttk.Treeview(wrap, columns=columns, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        for col, width in zip(columns, widths):
            anchor = "e" if col in ("Dauer", "Anteil") else "w"
            tree.heading(col, text=col, anchor=anchor,
                         command=lambda c=col, t=tree: self._sort_tree(t, c))
            tree.column(col, width=width, minwidth=48, anchor=anchor,
                        stretch=(col == stretch_col))
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        tree._sort_state = {}  # type: ignore[attr-defined]
        return tree

    # -- Daten laden & darstellen ------------------------------------
    def _current_segments(self):
        sel = self.selection.get()
        if sel == "week":
            return reporting.load_range(self.db, self.range_days[0], self.range_days[-1])
        return reporting.load_day(self.db, sel)

    def _refresh(self) -> None:
        try:
            segments = self._current_segments()
            summary = reporting.summarize(segments, self.config)
            self._segments = segments
            self._summary = summary
            self._update_cards(summary)
            self._fill_categories(summary)
            self._fill_apps(summary)
            self._fill_log(segments)
            self._fill_docs(summary)
            self._draw_chart()
            self.status.configure(
                text=f"Zuletzt aktualisiert {datetime.now():%H:%M:%S}  ·  "
                     f"{self.db.row_count()} Segmente in der Datenbank  ·  {DATA_DIR}"
            )
        except Exception:  # noqa: BLE001
            log.exception("Dashboard-Refresh fehlgeschlagen")

    def _update_cards(self, s: dict) -> None:
        self._cards["active"].configure(text=fmt_duration(s["total_active"], short=True))
        self._cards["idle"].configure(text=fmt_duration(s["total_idle"], short=True))
        self._cards["locked"].configure(text=fmt_duration(s["total_locked"], short=True))
        if s["first_activity"] and s["last_activity"]:
            self._cards["span"].configure(
                text=f"{s['first_activity']:%H:%M}–{s['last_activity']:%H:%M}"
            )
        else:
            self._cards["span"].configure(text="–")
        self._cards["switches"].configure(text=str(s["switches"]))
        lf = s["longest_focus"]
        self._cards["focus"].configure(
            text=fmt_duration(lf["seconds"], short=True) if lf["app"] else "–"
        )
        is_week = self.selection.get() == "week"
        goal_h = float(self.config.get("idle_goal_hours", 6.0))
        goal_total = goal_h * 3600 * (7 if is_week else 1)
        pct = (s["total_active"] / goal_total * 100) if goal_total else 0
        self._cards["goal"].configure(text=f"{pct:.0f}%")

    def _fill_categories(self, s: dict) -> None:
        self._reset_tree(self.cat_tree)
        for row in s["by_category"]:
            self.cat_tree.insert(
                "", "end",
                values=(row["label"], fmt_duration(row["seconds"], short=True), f"{row['pct']:.1f}%"),
                tags=(row["label"],),
            )
            self.cat_tree.tag_configure(row["label"], foreground=_cat_color(row["label"]))
        # Produktivität als zusätzliche Zeilen
        prod = s.get("productivity", {})
        if any(prod.values()):
            self.cat_tree.insert("", "end", values=("—", "", ""))
            for name in ("produktiv", "neutral", "ablenkend"):
                self.cat_tree.insert(
                    "", "end",
                    values=(f"Σ {name}", fmt_duration(prod.get(name, 0), short=True), ""),
                )

    def _fill_apps(self, s: dict) -> None:
        self._reset_tree(self.app_tree)
        # App -> Kategorie über die Segmente ermitteln
        cat_by_app: dict[str, str] = {}
        for seg in getattr(self, "_segments", []):
            if seg.state == "active":
                cat_by_app.setdefault(seg.app, seg.category)
        for row in s["by_app"]:
            cat = cat_by_app.get(row["label"], "")
            self.app_tree.insert(
                "", "end",
                values=(row["label"], cat, fmt_duration(row["seconds"], short=True), f"{row['pct']:.1f}%"),
                tags=(cat,),
            )
            self.app_tree.tag_configure(cat, foreground=_cat_color(cat))

    def _fill_log(self, segments) -> None:
        self._reset_tree(self.log_tree)
        states = ("active",) if self.log_filter.get() == "nur aktiv" else ("active", "idle", "locked")
        for e in reporting.timeline(segments, include_states=states):
            self.log_tree.insert(
                "", "end",
                values=(e["start"], e["end"], e["duration_h"], e["app"],
                        e["window"], e["category"], e["state"]),
                tags=(e["category"],),
            )
            self.log_tree.tag_configure(e["category"], foreground=_cat_color(e["category"]))

    def _fill_docs(self, s: dict) -> None:
        self._reset_tree(self.doc_tree)
        for row in s["by_document"][:400]:
            self.doc_tree.insert(
                "", "end",
                values=(row["app"], row["document"], fmt_duration(row["seconds"], short=True),
                        f"{row['pct']:.1f}%"),
            )

    # -- Diagramm ----------------------------------------------------
    def _draw_chart(self) -> None:
        if not hasattr(self, "_summary"):
            return
        c = self.chart
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 120 or h < 80:                       # Layout noch nicht fertig
            self.root.after(60, self._draw_chart)
            return
        pad_l, pad_r, pad_t, pad_b = 46, 16, 40, 28
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b

        if self.selection.get() == "week":
            labels, values, colors, title = self._week_series()
        else:
            labels, values, colors, title = self._day_series()

        c.create_text(pad_l - 40, 8, text=title, anchor="nw",
                      font=("Segoe UI Semibold", 10), fill="#334155")
        max_v = max(values) if values and max(values) > 0 else 1.0
        for frac in (0, 0.25, 0.5, 0.75, 1.0):
            y = pad_t + plot_h * (1 - frac)
            c.create_line(pad_l, y, w - pad_r, y, fill="#eef2f7")
            c.create_text(pad_l - 6, y, text=f"{max_v / 3600 * frac:.1f}h", anchor="e",
                          font=("Segoe UI", 7), fill="#94a3b8")

        n = max(1, len(values))
        slot = plot_w / n
        bar_w = min(46, slot * 0.66)
        baseline = pad_t + plot_h
        for i, (val, color) in enumerate(zip(values, colors)):
            cx = pad_l + slot * i + slot / 2
            bh = plot_h * (val / max_v)
            y0 = baseline - bh
            if val > 0:
                c.create_rectangle(cx - bar_w / 2, y0, cx + bar_w / 2, baseline,
                                   fill=color, outline="")
                if bh > 26:
                    c.create_text(cx, y0 + 9, text=fmt_duration(val, short=True),
                                  font=("Segoe UI", 7), fill="#ffffff")
                else:
                    c.create_text(cx, y0 - 8, text=fmt_duration(val, short=True),
                                  font=("Segoe UI", 7), fill="#475569")
        for i, label in enumerate(labels):
            if label:
                c.create_text(pad_l + slot * i + slot / 2, baseline + 13, text=label,
                              font=("Segoe UI", 7), fill="#64748b")

    def _week_series(self):
        s = self._summary
        labels, values, colors = [], [], []
        for day in self.range_days:
            d = datetime.strptime(day, "%Y-%m-%d")
            labels.append(f"{WEEKDAYS[d.weekday()]} {d.strftime('%d.%m')}")
            values.append(s["by_day"].get(day, {}).get("active", 0.0))
            colors.append("#2563eb")
        return labels, values, colors, "Aktive Zeit pro Tag"

    def _day_series(self):
        buckets = reporting.hourly_active(self._segments)
        labels = [f"{h:02d}" if h % 3 == 0 else "" for h in range(24)]
        colors = ["#2563eb"] * 24
        return labels, buckets, colors, "Aktive Zeit pro Stunde"

    # -- Tabellen-Helfer -------------------------------------------
    @staticmethod
    def _reset_tree(tree: ttk.Treeview) -> None:
        tree.delete(*tree.get_children())

    @staticmethod
    def _sort_tree(tree: ttk.Treeview, col: str) -> None:
        state = tree._sort_state  # type: ignore[attr-defined]
        reverse = not state.get(col, False)
        state.clear()
        state[col] = reverse

        def key(item):
            raw = tree.set(item, col)
            return reporting_sort_key(raw)

        rows = sorted(tree.get_children(""), key=key, reverse=reverse)
        for idx, item in enumerate(rows):
            tree.move(item, "", idx)

    # -- Aktionen -------------------------------------------------
    def _export(self, fmt: str) -> None:
        segments = self._current_segments()
        if not segments:
            messagebox.showinfo("Export", "Für diesen Zeitraum liegen keine Daten vor.")
            return
        default = f"timetracker_{self.selection.get()}_{datetime.now():%Y%m%d_%H%M%S}.{fmt}"
        path = filedialog.asksaveasfilename(
            initialdir=str(EXPORT_DIR), initialfile=default,
            defaultextension=f".{fmt}",
            filetypes=[(fmt.upper(), f"*.{fmt}"), ("Alle Dateien", "*.*")],
        )
        if not path:
            return
        content = (reporting.export_csv(segments) if fmt == "csv"
                   else reporting.export_json(segments, self.config))
        with open(path, "w", encoding="utf-8-sig" if fmt == "csv" else "utf-8", newline="") as fh:
            fh.write(content)
        messagebox.showinfo("Export", f"Gespeichert:\n{path}")

    def _open_folder(self) -> None:
        try:
            os.startfile(str(DATA_DIR))  # type: ignore[attr-defined]
        except AttributeError:
            subprocess.Popen(["explorer", str(DATA_DIR)])

    # -- Lebenszyklus --------------------------------------------
    def _schedule(self, ms: int, fn) -> None:
        self._after_jobs.append(self.root.after(ms, fn))

    def _auto_refresh(self) -> None:
        self._refresh()
        self._schedule(30_000, self._auto_refresh)

    def _watch_shutdown(self) -> None:
        if self.shutdown_event is not None and self.shutdown_event.is_set():
            self.close()
            return
        self._schedule(500, self._watch_shutdown)

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        for job in self._after_jobs:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self._after_jobs.clear()
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass


def reporting_sort_key(raw: str):
    """Sortierschlüssel: erkennt Dauer ('1h 02m'), Prozent und Zeiten."""
    txt = raw.strip()
    if txt.endswith("%"):
        try:
            return float(txt[:-1].replace(",", "."))
        except ValueError:
            return 0.0
    # Dauer wie "1h 02m 03s" / "2m 05s" / "45s"
    import re
    m = re.findall(r"(\d+)\s*([hms])", txt)
    if m:
        secs = 0
        for value, unit in m:
            secs += int(value) * {"h": 3600, "m": 60, "s": 1}[unit]
        return float(secs)
    if re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", txt):
        parts = [int(p) for p in txt.split(":")]
        while len(parts) < 3:
            parts.append(0)
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    try:
        return float(txt.replace(",", "."))
    except ValueError:
        return txt.lower()


def open_dashboard(db: Database, config: Config, shutdown_event: threading.Event | None = None) -> None:
    """Blockiert bis das Fenster geschlossen wird – im aufrufenden Thread ausführen."""
    Dashboard(db, config, shutdown_event).run()
