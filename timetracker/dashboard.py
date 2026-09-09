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

from . import reporting, theme
from .config import EXPORT_DIR, DATA_DIR, Config
from .database import Database
from .reporting import fmt_duration

log = logging.getLogger(__name__)

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


class Dashboard:
    def __init__(self, db: Database, config: Config, shutdown_event: threading.Event | None = None):
        self.db = db
        self.config = config
        self.shutdown_event = shutdown_event
        self._after_jobs: list[str] = []
        self._visible = True

        self.root = tk.Tk()
        self.root.title("TimeTracker – Dashboard")
        self.root.geometry("1130x760")
        self.root.minsize(940, 600)
        self._set_window_icon()

        self.range_days = reporting.last_n_days(7)
        self.selection = tk.StringVar(value="week")
        self.log_filter = tk.StringVar(value="alle")
        # Detailansicht = pro Datei; sonst pro Projekt zusammengefasst
        self.detail_view = tk.BooleanVar(
            value=not bool(config.get("collapse_editor_projects", True))
        )
        self._style = ttk.Style(self.root)
        self._nb_tab = 0

        self._build_all()

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._refresh()
        self._schedule(30_000, self._auto_refresh)
        self._watch_shutdown()

    # -- Aufbau ---------------------------------------------------------
    def _build_all(self) -> None:
        self.mode = theme.resolve(self.config.get("theme", "system"))
        self.pal = theme.apply(self._style, self.root, self.mode)
        self.cat_colors = theme.category_colors(self.mode)
        theme.set_titlebar(self.root, self.mode)
        self._build_toolbar()
        self._build_cards()
        self._build_notebook()
        self._build_statusbar()

    def _rebuild(self) -> None:
        """Kompletter Neuaufbau der Oberfläche (z. B. nach Theme-Wechsel).

        Fenstergröße/-zustand (maximiert, Vollbild) bleiben erhalten.
        """
        try:
            self._nb_tab = self._nb.index(self._nb.select())
        except Exception:  # noqa: BLE001
            pass
        try:
            win_state = self.root.state()
            fullscreen = bool(self.root.attributes("-fullscreen"))
            geometry = self.root.geometry()
        except tk.TclError:
            win_state, fullscreen, geometry = "normal", False, ""

        for widget in list(self.root.winfo_children()):
            widget.destroy()
        self._build_all()
        try:
            self._nb.select(self._nb_tab)
        except Exception:  # noqa: BLE001
            pass

        try:
            if fullscreen:
                self.root.attributes("-fullscreen", True)
            elif win_state == "zoomed":
                self.root.state("zoomed")
            elif geometry:
                self.root.geometry(geometry)
        except tk.TclError:
            pass
        self._refresh()

    def _cat_color(self, name: str) -> str:
        return self.cat_colors.get(name, self.pal["text_muted"])

    def _row_color(self, app: str, category: str) -> str:
        """Farbe für eine Zeile: eigene App-Farbe, sonst Kategorie-Farbe."""
        custom = self.config.app_colors.get(app)
        return custom or self._cat_color(category)

    def _on_detail_toggle(self) -> None:
        self.config.data["collapse_editor_projects"] = not self.detail_view.get()
        self.config.save()
        self._refresh()

    # -- App-Darstellung (Farbe + Kategorie) bearbeiten ----------
    def _on_app_tree_click(self, event) -> None:
        tree = self.app_tree
        if tree.identify_region(event.x, event.y) != "cell":
            return
        last_col = f"#{len(tree._columns)}"  # type: ignore[attr-defined]  – die ✎-Spalte
        if tree.identify_column(event.x) != last_col:
            return
        item = tree.identify_row(event.y)
        if item:
            self._edit_app_style(tree.item(item, "values")[0])

    def _known_categories(self) -> set[str]:
        cats: set[str] = set(self.config.productivity)          # inkl. interne Defaults
        for rule in self.config.categories:
            cats.add(rule.get("category", ""))
        cats.update(self.config.app_categories.values())
        for seg in getattr(self, "_segments", []):
            if seg.category:
                cats.add(seg.category)
        cats.discard("")
        return cats

    def _edit_app_style(self, app: str) -> None:
        from .appstyle import AppStyleDialog

        AppStyleDialog(
            self.root, app_name=app, palette=self.pal, mode=self.mode,
            color=self.config.app_colors.get(app, ""),
            category=self.config.app_categories.get(app, ""),
            categories=self._known_categories(),
            on_apply=lambda color, category: self._save_app_style(app, color, category),
        )

    def _save_app_style(self, app: str, color: str, category: str) -> None:
        colors = dict(self.config.data.get("app_colors", {}))
        if color:
            colors[app] = color
        else:
            colors.pop(app, None)

        cats = dict(self.config.data.get("app_categories", {}))
        if category:
            cats[app] = category
            if category not in self.config.productivity:      # neue Kategorie "anlegen"
                prod = dict(self.config.data.get("productivity", {}))
                prod[category] = 0                            # neutral
                self.config.data["productivity"] = prod
        else:
            cats.pop(app, None)

        self.config.data["app_colors"] = colors
        self.config.data["app_categories"] = cats
        self.config.save()
        self._refresh()

    def _set_window_icon(self) -> None:
        """Fenster-/Taskleistensymbol = Tray-Icon (statt Standard-Tk-Feder)."""
        try:
            from .tray import icon_photo_data

            self._icon_img = tk.PhotoImage(data=icon_photo_data())
            self.root.iconphoto(True, self._icon_img)
        except Exception:  # noqa: BLE001
            log.debug("Fenster-Icon konnte nicht gesetzt werden", exc_info=True)

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
            bar, values=self._period_labels, state="readonly", width=20,
            font=("Segoe UI", 9),
        )
        try:
            self.period_box.current(self._period_values.index(self.selection.get()))
        except ValueError:
            self.period_box.current(0)
        self.period_box.bind("<<ComboboxSelected>>", self._on_period_change)
        self.period_box.pack(side="left")
        ttk.Button(bar, text="Aktualisieren", command=self._refresh).pack(side="left", padx=8)

        ttk.Button(bar, text="Ordner", width=8, command=self._open_folder).pack(side="right")
        ttk.Button(bar, text="JSON", width=6, command=lambda: self._export("json")).pack(side="right", padx=(0, 4))
        ttk.Button(bar, text="CSV", width=6, command=lambda: self._export("csv")).pack(side="right", padx=(0, 4))
        ttk.Label(bar, text="Export:").pack(side="right", padx=(8, 4))

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
        self._nb = nb
        dev = bool(self.config.get("developer_mode", False))

        # -- Tab: Übersicht -------------------------------------------
        tab_overview = ttk.Frame(nb, padding=8)
        nb.add(tab_overview, text="  Übersicht  ")
        self.chart = tk.Canvas(tab_overview, height=270, bg=self.pal["chart_bg"],
                               highlightthickness=1, highlightbackground=self.pal["border"])
        self.chart.pack(fill="x")
        self.chart.bind("<Configure>", lambda e: self._draw_chart())
        cat_wrap = ttk.LabelFrame(tab_overview, text="Kategorien  ·  Verteilung der aktiven Zeit", padding=6)
        cat_wrap.pack(fill="both", expand=True, pady=(8, 0))
        self.cat_tree = self._make_tree(cat_wrap, ("Kategorie", "Dauer", "Anteil"),
                                        widths=(360, 130, 100), stretch_col="Kategorie")

        # -- Tab: Apps ----------------------------------------------
        tab_apps = ttk.Frame(nb, padding=8)
        nb.add(tab_apps, text="  Apps  ")
        ttk.Label(tab_apps, text="Klick auf  ✎  öffnet Farbe & Kategorie der App.",
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 4))
        self.app_tree = self._make_tree(
            tab_apps, ("App", "Kategorie", "Dauer", "Anteil", "✎"),
            widths=(300, 240, 120, 90, 34), stretch_col="Kategorie",
        )
        self.app_tree.bind("<Button-1>", self._on_app_tree_click)

        # -- Tab: Verlauf -----------------------------------------
        tab_log = ttk.Frame(nb, padding=8)
        nb.add(tab_log, text="  Verlauf  ")
        fbar = ttk.Frame(tab_log)
        fbar.pack(fill="x", pady=(0, 4))
        ttk.Label(fbar, text="Anzeigen:").pack(side="left")
        for lbl in ("alle", "nur aktiv"):
            ttk.Radiobutton(fbar, text=lbl, value=lbl, variable=self.log_filter,
                            command=self._refresh).pack(side="left", padx=4)
        ttk.Checkbutton(fbar, text="Detailansicht (pro Datei)", variable=self.detail_view,
                        command=self._on_detail_toggle).pack(side="left", padx=16)
        log_cols = ["Datum", "Von", "Bis", "Dauer", "App"]
        log_w = [118, 62, 62, 104, 214]
        if dev:
            log_cols.append("Branch"); log_w.append(140)
        log_cols += ["Fenster / Datei", "Kategorie", "Status"]
        log_w += [300, 176, 112]
        self.log_tree = self._make_tree(tab_log, tuple(log_cols), tuple(log_w),
                                        stretch_col="Fenster / Datei")

        # -- Tab: Dateien / Fenster ------------------------------
        tab_docs = ttk.Frame(nb, padding=8)
        nb.add(tab_docs, text="  Dateien / Fenster  ")
        dbar = ttk.Frame(tab_docs)
        dbar.pack(fill="x", pady=(0, 4))
        ttk.Checkbutton(dbar, text="Detailansicht (pro Datei)", variable=self.detail_view,
                        command=self._on_detail_toggle).pack(side="left")
        doc_cols = ["App"]
        doc_w = [230]
        if dev:
            doc_cols.append("Branch"); doc_w.append(140)
        doc_cols += ["Fenster / Datei", "Dauer", "Anteil"]
        doc_w += [430, 120, 90]
        self.doc_tree = self._make_tree(tab_docs, tuple(doc_cols), tuple(doc_w),
                                        stretch_col="Fenster / Datei")

        # -- Tab: Einstellungen ---------------------------------
        from .settings import SettingsPanel

        settings_tab = ttk.Frame(nb, padding=4)
        nb.add(settings_tab, text="  Einstellungen  ")
        self._settings_index = nb.index("end") - 1
        self._settings_panel = SettingsPanel(
            settings_tab, self.config, self.pal, on_saved=self._on_settings_saved
        )
        self._settings_panel.pack(fill="both", expand=True)

    def _build_statusbar(self) -> None:
        self.status = ttk.Label(self.root, text="", anchor="w", padding=(10, 3),
                                style="Status.TLabel")
        self.status.pack(fill="x")

    def _make_tree(self, parent, columns, widths, stretch_col: str | None = None) -> ttk.Treeview:
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True)
        tree = ttk.Treeview(wrap, columns=columns, show="headings", selectmode="extended")
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        for col, width in zip(columns, widths):
            if col in ("Dauer", "Anteil"):
                anchor = "e"
            elif col in ("Datum", "Von", "Bis", "Status", "✎"):
                anchor = "center"
            else:
                anchor = "w"
            heading_cmd = "" if col == "✎" else (lambda c=col, t=tree: self._sort_tree(t, c))
            tree.heading(col, text=col, anchor=anchor, command=heading_cmd)
            tree.column(col, width=width, minwidth=(28 if col == "✎" else 44), anchor=anchor,
                        stretch=(col == stretch_col))
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        tree._active_sort = (None, None)  # type: ignore[attr-defined]  (Spalte, absteigend?)
        tree._full_rows = {}    # type: ignore[attr-defined]  Item -> volle Werte (z. B. ganzer Titel)
        tree._columns = tuple(columns)  # type: ignore[attr-defined]
        self._install_copy(tree)
        return tree

    def _install_copy(self, tree: ttk.Treeview) -> None:
        """Strg+C / Rechtsklick → markierte Zeilen als Tabulator-Text in die Zwischenablage."""
        def as_text(items, with_header: bool) -> str:
            cols = tree._columns  # type: ignore[attr-defined]
            lines = ["\t".join(cols)] if with_header else []
            for it in items:
                full = tree._full_rows.get(it)  # type: ignore[attr-defined]
                vals = full if full else [str(v) for v in tree.item(it, "values")]
                lines.append("\t".join("" if v is None else str(v) for v in vals))
            return "\n".join(lines)

        def copy(which: str = "sel"):
            items = tree.get_children("") if which == "all" else tree.selection()
            if not items:
                return "break"
            text = as_text(items, with_header=(which == "all" or len(items) > 1))
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update_idletasks()
            status = getattr(self, "status", None)
            if status is not None:
                status.configure(text=f"{len(items)} Zeile(n) in die Zwischenablage kopiert.")
            return "break"

        def select_all(_event=None):
            tree.selection_set(tree.get_children(""))
            return "break"

        tree._copy = copy  # type: ignore[attr-defined]
        tree.bind("<Control-c>", lambda e: copy("sel"))
        tree.bind("<Control-C>", lambda e: copy("sel"))
        tree.bind("<Control-Insert>", lambda e: copy("sel"))
        tree.bind("<Control-a>", select_all)
        tree.bind("<Control-A>", select_all)

        menu = tk.Menu(tree, tearoff=False, bg=self.pal["surface"], fg=self.pal["text"],
                       activebackground=self.pal["sel_bg"], activeforeground=self.pal["sel_fg"])
        menu.add_command(label="Auswahl kopieren\tStrg+C", command=lambda: copy("sel"))
        menu.add_command(label="Ganze Tabelle kopieren", command=lambda: copy("all"))

        def popup(event):
            row = tree.identify_row(event.y)
            if row and row not in tree.selection():
                tree.selection_set(row)
            if tree.selection():
                menu.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", popup)

    # -- Daten laden & darstellen ------------------------------------
    def _current_segments(self):
        sel = self.selection.get()
        if sel == "week":
            segs = reporting.load_range(self.db, self.range_days[0], self.range_days[-1])
        else:
            segs = reporting.load_day(self.db, sel)
        reporting.apply_category_overrides(segs, self.config)  # eigene App-Kategorien rückwirkend
        if not self.detail_view.get():
            segs = reporting.collapse_projects(segs, self.config)
        return segs

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
            self.cat_tree.tag_configure(row["label"], foreground=self._cat_color(row["label"]))
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
        cat_by_app: dict[str, str] = {}
        for seg in getattr(self, "_segments", []):
            if seg.state == "active":
                cat_by_app.setdefault(seg.app, seg.category)
        self._cat_by_app = cat_by_app
        for row in s["by_app"]:
            app = row["label"]
            cat = cat_by_app.get(app, "")
            color = self._row_color(app, cat)
            vals = (app, cat, fmt_duration(row["seconds"], short=True), f"{row['pct']:.1f}%", "✎")
            item = self.app_tree.insert("", "end", values=vals, tags=(color,))
            self.app_tree._full_rows[item] = list(vals[:-1])  # type: ignore[attr-defined]
            self.app_tree.tag_configure(color, foreground=color)

    def _fill_log(self, segments) -> None:
        self._reset_tree(self.log_tree)
        dev = "Branch" in self.log_tree._columns  # type: ignore[attr-defined]
        states = ("active",) if self.log_filter.get() == "nur aktiv" else ("active", "idle", "locked")
        entries = reporting.timeline(segments, include_states=states)
        for e in reversed(entries):  # Standard: neueste Einträge oben
            row = [e["date"], e["start"], e["end"], e["duration_h"], e["app"]]
            full = [e["date"], e["start_iso"], e["end_iso"], e["duration_h"], e["app"]]
            if dev:
                row.append(e["branch"])
                full.append(e["branch"])
            row += [e["window"], e["category"], e["state"]]
            full += [e["title"] or e["window"], e["category"], e["state"]]
            color = self._row_color(e["app"], e["category"])
            item = self.log_tree.insert("", "end", values=tuple(row), tags=(color,))
            self.log_tree._full_rows[item] = full  # type: ignore[attr-defined]
            self.log_tree.tag_configure(color, foreground=color)
        self._apply_saved_sort(self.log_tree)

    def _fill_docs(self, s: dict) -> None:
        self._reset_tree(self.doc_tree)
        dev = "Branch" in self.doc_tree._columns  # type: ignore[attr-defined]
        for row in s["by_document"][:400]:
            vals = [row["app"]]
            if dev:
                vals.append(row.get("branch", ""))
            vals += [row["document"], fmt_duration(row["seconds"], short=True), f"{row['pct']:.1f}%"]
            color = self._row_color(row["app"], row.get("category", ""))
            item = self.doc_tree.insert("", "end", values=tuple(vals), tags=(color,))
            self.doc_tree._full_rows[item] = list(vals)  # type: ignore[attr-defined]
            self.doc_tree.tag_configure(color, foreground=color)

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
                      font=("Segoe UI Semibold", 10), fill=self.pal["text"])
        max_v = max(values) if values and max(values) > 0 else 1.0
        for frac in (0, 0.25, 0.5, 0.75, 1.0):
            y = pad_t + plot_h * (1 - frac)
            c.create_line(pad_l, y, w - pad_r, y, fill=self.pal["grid"])
            c.create_text(pad_l - 6, y, text=f"{max_v / 3600 * frac:.1f}h", anchor="e",
                          font=("Segoe UI", 7), fill=self.pal["text_muted"])

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
                                  font=("Segoe UI", 7), fill=self.pal["bar_label_on"])
                else:
                    c.create_text(cx, y0 - 8, text=fmt_duration(val, short=True),
                                  font=("Segoe UI", 7), fill=self.pal["bar_label_off"])
        for i, label in enumerate(labels):
            if label:
                c.create_text(pad_l + slot * i + slot / 2, baseline + 13, text=label,
                              font=("Segoe UI", 7), fill=self.pal["text_muted"])

    def _week_series(self):
        s = self._summary
        labels, values, colors = [], [], []
        for day in self.range_days:
            d = datetime.strptime(day, "%Y-%m-%d")
            labels.append(f"{WEEKDAYS[d.weekday()]} {d.strftime('%d.%m')}")
            values.append(s["by_day"].get(day, {}).get("active", 0.0))
            colors.append(self.pal["bar"])
        return labels, values, colors, "Aktive Zeit pro Tag"

    def _day_series(self):
        buckets = reporting.hourly_active(self._segments)
        labels = [f"{h:02d}" if h % 3 == 0 else "" for h in range(24)]
        colors = [self.pal["bar"]] * 24
        return labels, buckets, colors, "Aktive Zeit pro Stunde"

    # -- Tabellen-Helfer -------------------------------------------
    @staticmethod
    def _reset_tree(tree: ttk.Treeview) -> None:
        tree.delete(*tree.get_children())
        if hasattr(tree, "_full_rows"):
            tree._full_rows.clear()  # type: ignore[attr-defined]

    def _sort_tree(self, tree: ttk.Treeview, col: str) -> None:
        prev_col, prev_rev = getattr(tree, "_active_sort", (None, None))
        reverse = (not prev_rev) if col == prev_col else False
        tree._active_sort = (col, reverse)  # type: ignore[attr-defined]
        self._do_sort(tree, col, reverse)

    @staticmethod
    def _do_sort(tree: ttk.Treeview, col: str, reverse: bool) -> None:
        rows = sorted(tree.get_children(""),
                      key=lambda i: reporting_sort_key(tree.set(i, col)), reverse=reverse)
        for idx, item in enumerate(rows):
            tree.move(item, "", idx)
        for c in getattr(tree, "_columns", ()):  # type: ignore[attr-defined]
            arrow = ("  ▼" if reverse else "  ▲") if c == col else ""
            tree.heading(c, text=c + arrow)

    @staticmethod
    def _apply_saved_sort(tree: ttk.Treeview) -> None:
        active = getattr(tree, "_active_sort", None)
        if active and active[0]:
            Dashboard._do_sort(tree, active[0], active[1])

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

    def open_settings(self) -> None:
        """Wechselt auf den Einstellungen-Tab (kein separates Fenster)."""
        try:
            self._nb.select(self._settings_index)
        except (AttributeError, tk.TclError):
            pass

    def _on_settings_saved(self, data: dict) -> None:
        from . import autostart
        old_mode = getattr(self, "mode", theme.resolve(self.config.get("theme", "system")))
        try:
            want = bool(data.get("autostart"))
            if want and not autostart.is_enabled():
                autostart.enable()
            elif not want and autostart.is_enabled():
                autostart.disable()
        except Exception:  # noqa: BLE001
            log.exception("Autostart-Änderung fehlgeschlagen")

        if "collapse_editor_projects" in data:  # nur beim Zurücksetzen enthalten
            self.detail_view.set(not bool(data["collapse_editor_projects"]))
        theme_changed = theme.resolve(data.get("theme", self.config.get("theme"))) != old_mode
        dev_changed = bool(data.get("developer_mode")) != (
            "Branch" in getattr(self.log_tree, "_columns", ())
        )
        if theme_changed or dev_changed:
            self.root.after(50, lambda: (self._rebuild(), self._nb.select(0)))
        else:
            self._nb.select(0)
            self._refresh()

    # -- Lebenszyklus --------------------------------------------
    def _schedule(self, ms: int, fn) -> None:
        self._after_jobs.append(self.root.after(ms, fn))

    def _auto_refresh(self) -> None:
        if self._visible:                     # ausgeblendet: nicht sinnlos die DB abfragen
            self._refresh()
        self._schedule(30_000, self._auto_refresh)

    def _watch_shutdown(self) -> None:
        if self.shutdown_event is not None and self.shutdown_event.is_set():
            self.shutdown()
            return
        self._schedule(500, self._watch_shutdown)

    def run(self) -> None:
        self.root.mainloop()

    def show(self) -> None:
        """Fenster wieder einblenden (Tray-Klick)."""
        self._visible = True
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            return
        self._refresh()

    def close(self) -> None:
        """Nur ausblenden – Thread und Tk-Interpreter bleiben am Leben.

        Früher wurde hier ``root.destroy()`` aufgerufen und beim nächsten Öffnen
        ein neues ``Tk()`` in einem neuen Thread erzeugt. Sobald die
        Garbage-Collection später die Reste des alten Dashboards aufräumte, lief
        ``Tcl_DeleteInterp`` im falschen Thread → Tcl-Panic (0x80000003), der
        ganze Prozess brach hart ab.
        """
        self._visible = False
        try:
            self.root.withdraw()
        except tk.TclError:
            pass

    def shutdown(self) -> None:
        """Endgültig schließen – nur beim Beenden der App.

        Läuft im Dashboard-Thread (per ``root.after`` bzw. ``_watch_shutdown``).
        """
        root = self.root
        if root is None:                       # schon heruntergefahren
            return
        for job in self._after_jobs:
            try:
                root.after_cancel(job)
            except tk.TclError:
                pass
        self._after_jobs.clear()
        try:
            root.quit()
            root.destroy()
        except tk.TclError:
            pass
        # Verbleibende Tk-Wrapper (Variablen, PhotoImage, Widgets) JETZT im eigenen
        # Thread einsammeln. Sonst finalisiert sie später der GC eines anderen
        # Threads → „Tcl_AsyncDelete: async handler deleted by the wrong thread".
        import gc
        for name in list(self.__dict__):
            setattr(self, name, None)
        gc.collect()


def reporting_sort_key(raw: str):
    """Sortierschlüssel: erkennt Datum ('27.08.2026'), Dauer ('1h 02m'), Prozent, Zeiten."""
    txt = raw.strip().rstrip(" ▲▼")
    if txt.endswith("%"):
        try:
            return float(txt[:-1].replace(",", "."))
        except ValueError:
            return 0.0
    import re
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", txt):
        d, m, y = txt.split(".")
        return float(y + m + d)
    # Dauer wie "1h 02m 03s" / "2m 05s" / "45s"
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
    """Blockiert bis das Fenster geschlossen wird – im aufrufenden Thread ausführen.

    Eigenständiger Aufruf (CLI ``timetracker dashboard``): das Schließen des
    Fensters beendet hier wirklich – nicht nur ausblenden wie im Tray-Betrieb.
    """
    dash = Dashboard(db, config, shutdown_event)
    dash.root.protocol("WM_DELETE_WINDOW", dash.shutdown)
    dash.run()
