"""Einstellungs-Dialog – bearbeitet alle Optionen aus ``config.json`` als Formular."""
from __future__ import annotations

import json
import logging

import tkinter as tk
from tkinter import messagebox, ttk

from . import theme
from .config import DEFAULTS, Config

log = logging.getLogger(__name__)

# (Abschnitt, key, Beschriftung, Art, Extra, Hilfetext)
#   Art:  bool | int | float | choice | lines | json
_SPEC: list[tuple] = [
    ("Erfassung", "poll_interval_seconds", "Abtastintervall (Sekunden)", "int", (1, 60),
     "Wie oft das aktive Fenster geprüft wird. Kleiner = genauer, minimal mehr CPU. Wirkt sofort."),
    ("Erfassung", "idle_threshold_seconds", "Als „abwesend“ zählen ab (Sekunden ohne Eingabe)", "int", (10, 7200),
     "Bis dahin wird die Zeit weiter der App zugerechnet, danach als „Abwesend“."),
    ("Erfassung", "min_segment_seconds", "Kürzeste erfasste Dauer (Sekunden)", "int", (0, 120),
     "Einträge kürzer als dieser Wert werden verworfen (schnelles Durchklicken)."),
    ("Erfassung", "track_titles", "Fenstertitel und Dateinamen speichern", "bool", None,
     "Aus: es wird nur der Programmname erfasst, kein Titel/keine Datei."),

    ("Daten & Anzeige", "retention_days", "Daten aufbewahren (Tage)", "int", (7, 3650),
     "Ältere Einträge werden automatisch gelöscht. Minimum 7."),
    ("Daten & Anzeige", "idle_goal_hours", "Tagesziel aktive Zeit (Stunden)", "float", (0.0, 24.0),
     "Basis für die „Tagesziel“-Kachel im Dashboard."),
    ("Daten & Anzeige", "theme", "Design", "choice",
     [("System (Windows)", "system"), ("Hell", "light"), ("Dunkel", "dark")],
     "„System“ folgt der Hell/Dunkel-Einstellung von Windows."),

    ("Autostart", "autostart", "TimeTracker mit Windows starten", "bool", None,
     "Trägt einen Eintrag im Autostart des aktuellen Benutzers ein (HKCU…\\Run)."),

    ("Datenschutz", "private_processes", "Private Programme  –  ein .exe pro Zeile", "lines", None,
     "Für diese Programme werden weder Titel noch Datei gespeichert (z. B. Passwort-Manager)."),
    ("Datenschutz", "private_title_patterns", "Private Titel-Muster  –  ein Regex pro Zeile", "lines", None,
     "Fenster, deren Titel darauf passt, werden ohne Details erfasst (z. B. „passwort“, „banking“)."),

    ("Ignorieren", "ignore_processes", "Ignorierte Programme  –  ein .exe pro Zeile", "lines", None,
     "Transiente Shell-Fenster (Startmenü, Suche …). Der laufende Eintrag wird dadurch nicht unterbrochen."),
    ("Ignorieren", "ignore_title_patterns", "Ignorierte Titel-Muster  –  eines pro Zeile", "lines", None,
     "z. B. „Überlauffenster der Taskleiste“, „Task-Umschalten“."),

    ("Erweitert", "app_names", "Eigene Anzeigenamen  (JSON-Objekt)", "json", dict,
     'Prozessname → Anzeigename.  Beispiel:  {"meinprog.exe": "Mein Programm"}'),
    ("Erweitert", "categories", "Kategorie-Regeln  (JSON-Liste)", "json", list,
     'Leere Liste = interne Vorgaben.  '
     '[{"category": "Meine Firma", "processes": ["sap.exe"], "title_patterns": ["JIRA"]}]'),
    ("Erweitert", "productivity", "Produktivität je Kategorie  (JSON-Objekt)", "json", dict,
     '1 = produktiv, 0 = neutral, -1 = ablenkend.  Beispiel:  {"Entwicklung": 1, "Gaming": -1}'),
]


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, config: Config, palette: dict,
                 on_saved=None, on_close=None):
        super().__init__(parent)
        self.config = config
        self.pal = palette
        self.on_saved = on_saved
        self.on_close = on_close
        self._vars: dict[str, object] = {}
        self._widgets: dict[str, tk.Widget] = {}

        self.title("TimeTracker – Einstellungen")
        self.configure(bg=palette["bg"])
        self.transient(parent)
        self.resizable(False, False)
        self._mode = "dark" if palette is theme.PALETTES["dark"] else "light"
        self._build()
        theme.set_titlebar(self, self._mode)

        self.bind("<Escape>", lambda _e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx() + 60}+{parent.winfo_rooty() + 30}")
        self.grab_set()
        self.focus_set()

    # -- Aufbau ---------------------------------------------------------
    def _build(self) -> None:
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        frames: dict[str, ttk.Frame] = {}
        for section, key, label, kind, extra, helptext in _SPEC:
            frame = frames.get(section)
            if frame is None:
                frame = ttk.Frame(nb, padding=14)
                frame.columnconfigure(0, weight=1)
                frame._row = 0  # type: ignore[attr-defined]
                nb.add(frame, text=f"  {section}  ")
                frames[section] = frame
            self._add_field(frame, key, label, kind, extra, helptext)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Auf Standard zurücksetzen", command=self._reset).pack(side="left")
        ttk.Button(btns, text="Speichern", style="Accent.TButton",
                   command=self._save).pack(side="right")
        ttk.Button(btns, text="Abbrechen", command=self._close).pack(side="right", padx=6)

    def _text_widget(self, parent, height: int) -> tk.Text:
        return tk.Text(parent, height=height, width=58, font=("Consolas", 9), wrap="none",
                       bg=self.pal["surface"], fg=self.pal["text"],
                       insertbackground=self.pal["text"],
                       selectbackground=self.pal["sel_bg"], selectforeground=self.pal["sel_fg"],
                       relief="solid", borderwidth=1, highlightthickness=0)

    def _add_field(self, parent, key, label, kind, extra, helptext) -> None:
        row = parent._row  # type: ignore[attr-defined]
        ttk.Label(parent, text=label, font=("Segoe UI Semibold", 9)).grid(
            row=row, column=0, sticky="w", pady=(10, 2), columnspan=2)

        cur = self.config.get(key, DEFAULTS.get(key))
        var: object = None

        if kind == "bool":
            var = tk.BooleanVar(value=bool(cur))
            ttk.Checkbutton(parent, variable=var, text="aktiviert").grid(
                row=row + 1, column=0, sticky="w", columnspan=2)
        elif kind in ("int", "float"):
            lo, hi = extra
            var = tk.StringVar(value=str(cur))
            ttk.Spinbox(parent, from_=lo, to=hi, textvariable=var, width=16,
                        font=("Segoe UI", 10),
                        increment=(0.5 if kind == "float" else 1)).grid(
                row=row + 1, column=0, sticky="w")
        elif kind == "choice":
            labels = [lbl for lbl, _ in extra]
            mapping = {lbl: val for lbl, val in extra}
            current_label = next((lbl for lbl, val in extra if val == cur), labels[0])
            var = tk.StringVar(value=current_label)
            var._map = mapping  # type: ignore[attr-defined]
            ttk.Combobox(parent, values=labels, textvariable=var, state="readonly",
                         width=22).grid(row=row + 1, column=0, sticky="w")
        elif kind == "lines":
            widget = self._text_widget(parent, 5)
            widget.insert("1.0", "\n".join(cur or []))
            widget.grid(row=row + 1, column=0, sticky="we", columnspan=2)
            self._widgets[key] = widget
        elif kind == "json":
            widget = self._text_widget(parent, 8)
            widget.insert("1.0", json.dumps(cur, indent=2, ensure_ascii=False))
            widget.grid(row=row + 1, column=0, sticky="we", columnspan=2)
            self._widgets[key] = widget

        if helptext:
            ttk.Label(parent, text=helptext, style="Hint.TLabel",
                      wraplength=520, justify="left").grid(
                row=row + 2, column=0, sticky="w", columnspan=2, pady=(2, 0))

        self._vars[key] = var
        parent._row = row + 3  # type: ignore[attr-defined]

    # -- Speichern ----------------------------------------------------
    def _collect(self) -> dict | None:
        out: dict = {}
        for section, key, label, kind, extra, helptext in _SPEC:
            try:
                if kind == "bool":
                    out[key] = bool(self._vars[key].get())  # type: ignore[union-attr]
                elif kind == "int":
                    val = int(float(str(self._vars[key].get()).replace(",", ".")))  # type: ignore[union-attr]
                    out[key] = max(extra[0], min(extra[1], val))
                elif kind == "float":
                    val = float(str(self._vars[key].get()).replace(",", "."))  # type: ignore[union-attr]
                    out[key] = round(max(extra[0], min(extra[1], val)), 2)
                elif kind == "choice":
                    var = self._vars[key]
                    out[key] = var._map.get(var.get(), list(var._map.values())[0])  # type: ignore[union-attr]
                elif kind == "lines":
                    text = self._widgets[key].get("1.0", "end")
                    out[key] = [ln.strip() for ln in text.splitlines() if ln.strip()]
                elif kind == "json":
                    raw = self._widgets[key].get("1.0", "end").strip() or "null"
                    parsed = json.loads(raw)
                    if extra is list and not isinstance(parsed, list):
                        raise ValueError("Eine JSON-Liste [...] wird erwartet.")
                    if extra is dict and not isinstance(parsed, dict):
                        raise ValueError("Ein JSON-Objekt {...} wird erwartet.")
                    out[key] = parsed
            except (ValueError, json.JSONDecodeError) as exc:
                messagebox.showerror("Ungültige Eingabe", f"„{label}“:\n\n{exc}", parent=self)
                return None
        out["retention_days"] = max(7, int(out.get("retention_days", 90)))
        return out

    def _save(self) -> None:
        data = self._collect()
        if data is None:
            return
        self.config.data.update(data)
        self.config.save()
        cb = self.on_saved
        self._teardown()
        if cb:
            cb(data)

    def _reset(self) -> None:
        if not messagebox.askyesno(
            "Zurücksetzen", "Alle Einstellungen auf die Standardwerte zurücksetzen?", parent=self
        ):
            return
        for key in self._vars:
            self.config.data[key] = json.loads(json.dumps(DEFAULTS.get(key)))
        self.config.save()
        cb = self.on_saved
        self._teardown()
        if cb:
            cb(dict(self.config.data))

    def _close(self) -> None:
        cb = self.on_close
        self._teardown()
        if cb:
            cb()

    def _teardown(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
