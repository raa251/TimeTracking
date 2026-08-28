"""Einstellungen als Panel (Tab) im Hauptfenster – kein eigenes Fenster."""
from __future__ import annotations

import json
import logging

import tkinter as tk
from tkinter import messagebox, ttk

from .config import DEFAULTS, Config

log = logging.getLogger(__name__)

# (Abschnitt, key, Beschriftung, Art, Extra, Hilfetext)
#   Art:  bool | int | float | choice | lines | json
_SPEC: list[tuple] = [
    ("Erfassung", "poll_interval_seconds", "Abtastintervall (Sekunden)", "int", (1, 60),
     "Fester Takt, in dem das aktive Fenster geprüft wird (Standard 3s)."),
    ("Erfassung", "idle_threshold_seconds", "Als „abwesend“ zählen ab (Sekunden ohne Eingabe)", "int", (10, 7200),
     "Bis dahin wird die Zeit weiter der App zugerechnet, danach als „Abwesend“."),
    ("Erfassung", "keep_active_on_media", "Bei Video / Besprechung nicht auf „abwesend“", "bool", None,
     "Kein „Abwesend“, solange Ton läuft (Video/Stream), eine Vollbild-Wiedergabe aktiv ist "
     "oder Kamera/Mikrofon in Benutzung sind (Teams, Zoom …)."),
    ("Erfassung", "min_segment_seconds", "Kürzeste erfasste Dauer (Sekunden)", "int", (0, 600),
     "Einträge, die kürzer sind, werden nicht gespeichert. Bei Standard (3 s Takt) meist ohne "
     "Wirkung – höher stellen (z. B. 30), um kurze Blicke auf andere Fenster auszublenden."),
    ("Erfassung", "track_titles", "Fenstertitel und Dateinamen speichern", "bool", None,
     "Aus: es wird nur der Programmname erfasst, kein Titel/keine Datei."),

    ("Daten & Anzeige", "retention_days", "Daten aufbewahren (Tage)", "int", (7, 3650),
     "Ältere Einträge werden automatisch gelöscht. Minimum 7."),
    ("Daten & Anzeige", "idle_goal_hours", "Tagesziel aktive Zeit (Stunden)", "float", (0.0, 24.0),
     "Basis für die „Tagesziel“-Kachel im Dashboard."),
    ("Daten & Anzeige", "theme", "Design", "choice",
     [("System (Windows)", "system"), ("Hell", "light"), ("Dunkel", "dark")],
     "„System“ folgt der Hell/Dunkel-Einstellung von Windows."),
    ("Daten & Anzeige", "developer_mode", "Entwicklermodus (zeigt zusätzlich Branches an)", "bool", None,
     "Blendet in „Verlauf“ und „Dateien / Fenster“ eine Spalte mit dem Git-Branch ein. "
     "Die lokalen Repos werden automatisch gefunden (Home-Verzeichnis + Laufwerks-Ordner)."),

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
    ("Erweitert", "app_colors", "Eigene App-Farben  (JSON-Objekt)", "json", dict,
     'Bequemer über den Apps-Tab (✎).  Beispiel:  {"Visual Studio Code": "#2563eb"}'),
    ("Erweitert", "app_categories", "Eigene Kategorie je App  (JSON-Objekt)", "json", dict,
     'Bequemer über den Apps-Tab (✎).  Beispiel:  {"Visual Studio Code": "Meine Firma"}'),
    ("Erweitert", "categories", "Kategorie-Regeln  (JSON-Liste)", "json", list,
     'Leere Liste = interne Vorgaben.  '
     '[{"category": "Meine Firma", "processes": ["sap.exe"], "title_patterns": ["JIRA"]}]'),
    ("Erweitert", "productivity", "Produktivität je Kategorie  (JSON-Objekt)", "json", dict,
     '1 = produktiv, 0 = neutral, -1 = ablenkend.  Beispiel:  {"Entwicklung": 1, "Gaming": -1}'),
]


class SettingsPanel(ttk.Frame):
    """Scrollbares Formular für alle ``config.json``-Optionen – lebt als Tab im Dashboard."""

    def __init__(self, parent: tk.Misc, config: Config, palette: dict, on_saved=None, on_close=None):
        super().__init__(parent)
        self.config = config
        self.pal = palette
        self.on_saved = on_saved
        self.on_close = on_close
        self._vars: dict[str, object] = {}
        self._widgets: dict[str, tk.Widget] = {}
        self._build()

    # -- Aufbau -------------------------------------------------------
    def _build(self) -> None:
        btns = ttk.Frame(self, padding=(10, 8))
        btns.pack(fill="x", side="bottom")
        ttk.Button(btns, text="Auf Standard zurücksetzen", command=self._reset).pack(side="left")
        ttk.Button(btns, text="Speichern", style="Accent.TButton", command=self._save).pack(side="right")
        ttk.Button(btns, text="Verwerfen", command=self._revert).pack(side="right", padx=6)

        canvas = tk.Canvas(self, bg=self.pal["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        form = ttk.Frame(canvas, padding=(14, 10))
        form.columnconfigure(0, weight=1)
        window = canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))

        def _wheel(event):
            canvas.yview_scroll(int(-event.delta / 120), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        row = 0
        last_section = None
        for section, key, label, kind, extra, helptext in _SPEC:
            if section != last_section:
                ttk.Label(form, text=section, font=("Segoe UI Semibold", 11),
                          foreground=self.pal["accent"]).grid(
                    row=row, column=0, sticky="w", pady=(16 if last_section else 2, 2), columnspan=2)
                row += 1
                last_section = section
            row = self._add_field(form, row, key, label, kind, extra, helptext)

    def _text_widget(self, parent, height: int) -> tk.Text:
        return tk.Text(parent, height=height, width=54, font=("Consolas", 9), wrap="none",
                       bg=self.pal["surface"], fg=self.pal["text"],
                       insertbackground=self.pal["text"],
                       selectbackground=self.pal["sel_bg"], selectforeground=self.pal["sel_fg"],
                       relief="solid", borderwidth=1, highlightthickness=0)

    def _add_field(self, parent, row, key, label, kind, extra, helptext) -> int:
        ttk.Label(parent, text=label, font=("Segoe UI Semibold", 9)).grid(
            row=row, column=0, sticky="w", pady=(8, 2), columnspan=2)
        row += 1
        cur = self.config.get(key, DEFAULTS.get(key))
        var: object = None

        if kind == "bool":
            var = tk.BooleanVar(value=bool(cur))
            ttk.Checkbutton(parent, variable=var, text="aktiviert").grid(
                row=row, column=0, sticky="w", columnspan=2)
        elif kind in ("int", "float"):
            lo, hi = extra
            var = tk.StringVar(value=str(cur))
            ttk.Spinbox(parent, from_=lo, to=hi, textvariable=var, width=16,
                        font=("Segoe UI", 10),
                        increment=(0.5 if kind == "float" else 1)).grid(row=row, column=0, sticky="w")
        elif kind == "choice":
            labels = [lbl for lbl, _ in extra]
            var = tk.StringVar(value=next((lbl for lbl, val in extra if val == cur), labels[0]))
            var._map = {lbl: val for lbl, val in extra}  # type: ignore[attr-defined]
            ttk.Combobox(parent, values=labels, textvariable=var, state="readonly",
                         width=22).grid(row=row, column=0, sticky="w")
        elif kind in ("lines", "json"):
            widget = self._text_widget(parent, 5 if kind == "lines" else 6)
            widget.insert("1.0", "\n".join(cur or []) if kind == "lines"
                          else json.dumps(cur, indent=2, ensure_ascii=False))
            widget.grid(row=row, column=0, sticky="we", columnspan=2)
            self._widgets[key] = widget

        row += 1
        if helptext:
            ttk.Label(parent, text=helptext, style="Hint.TLabel",
                      wraplength=560, justify="left").grid(
                row=row, column=0, sticky="w", columnspan=2, pady=(2, 0))
            row += 1
        self._vars[key] = var
        return row

    # -- Werte einsammeln / speichern -------------------------------
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
        if self.on_saved:
            self.on_saved(data)

    def _reset(self) -> None:
        if not messagebox.askyesno(
            "Zurücksetzen", "Alle Einstellungen auf die Standardwerte zurücksetzen?", parent=self
        ):
            return
        for key in self._vars:
            self.config.data[key] = json.loads(json.dumps(DEFAULTS.get(key)))
        self.config.save()
        if self.on_saved:
            self.on_saved(dict(self.config.data))

    def _revert(self) -> None:
        """Formular wieder auf die gespeicherten Werte setzen."""
        for section, key, label, kind, extra, helptext in _SPEC:
            cur = self.config.get(key, DEFAULTS.get(key))
            if kind == "bool":
                self._vars[key].set(bool(cur))  # type: ignore[union-attr]
            elif kind in ("int", "float"):
                self._vars[key].set(str(cur))  # type: ignore[union-attr]
            elif kind == "choice":
                var = self._vars[key]
                inv = {v: k for k, v in var._map.items()}  # type: ignore[attr-defined]
                var.set(inv.get(cur, next(iter(var._map))))  # type: ignore[union-attr]
            elif kind in ("lines", "json"):
                w = self._widgets[key]
                w.delete("1.0", "end")
                w.insert("1.0", "\n".join(cur or []) if kind == "lines"
                         else json.dumps(cur, indent=2, ensure_ascii=False))
        if self.on_close:
            self.on_close()
