"""Themebewusster Dialog: Farbe und Kategorie einer App festlegen."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import colorchooser, ttk

from . import theme

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_AUTO = "(automatisch)"
_PRESETS = [
    "#2563eb", "#0ea5e9", "#0891b2", "#0d9488", "#16a34a", "#65a30d", "#f59e0b", "#ea580c",
    "#dc2626", "#f43f5e", "#db2777", "#c026d3", "#7c3aed", "#4f46e5", "#64748b", "#334155",
]


class AppStyleDialog(tk.Toplevel):
    """``on_apply(color: str, category: str)`` – leere Strings = zurücksetzen/automatisch."""

    def __init__(self, parent, *, app_name: str, palette: dict, mode: str,
                 color: str, category: str, categories, on_apply):
        super().__init__(parent)
        self.pal = palette
        self._app = app_name
        self._on_apply = on_apply

        self.title(f"Darstellung – {app_name}")
        self.configure(bg=palette["bg"])
        self.transient(parent)
        self.resizable(False, False)

        self._color = tk.StringVar(value=color or "")
        self._cat = tk.StringVar(value=category or _AUTO)

        self._build(sorted(c for c in categories if c))
        theme.set_titlebar(self, mode)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx() + 100}+{parent.winfo_rooty() + 80}")
        self.grab_set()
        self._hex_entry.focus_set()

    # -- Aufbau -----------------------------------------------------
    def _build(self, categories: list[str]) -> None:
        p = self.pal
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=self._app, font=("Segoe UI Semibold", 12)).grid(
            row=0, column=0, sticky="w", pady=(0, 10))

        # --- Farbe ---
        ttk.Label(outer, text="Farbe", font=("Segoe UI Semibold", 9)).grid(
            row=1, column=0, sticky="w")
        grid = tk.Frame(outer, bg=p["bg"])
        grid.grid(row=2, column=0, sticky="w", pady=(4, 6))
        self._swatches: dict[str, tk.Label] = {}
        for i, hexv in enumerate(_PRESETS):
            sw = tk.Label(grid, bg=hexv, width=2, height=1, relief="solid", bd=1, cursor="hand2")
            sw.grid(row=i // 8, column=i % 8, padx=2, pady=2)
            sw.bind("<Button-1>", lambda _e, h=hexv: self._set_color(h))
            self._swatches[hexv.lower()] = sw

        picker = tk.Frame(outer, bg=p["bg"])
        picker.grid(row=3, column=0, sticky="w")
        self._preview = tk.Label(picker, width=3, height=1, relief="solid", bd=1, bg=p["surface"])
        self._preview.pack(side="left", padx=(0, 8))
        self._hex_entry = tk.Entry(
            picker, textvariable=self._color, width=11, font=("Consolas", 10),
            bg=p["surface"], fg=p["text"], insertbackground=p["text"],
            disabledbackground=p["surface"], relief="solid", bd=1, highlightthickness=0,
        )
        self._hex_entry.pack(side="left")
        self._hex_entry.bind("<KeyRelease>", lambda _e: self._refresh_preview())
        ttk.Button(picker, text="Wählen …", width=10, command=self._pick).pack(side="left", padx=6)
        ttk.Button(picker, text="Standard", width=9,
                   command=lambda: self._set_color("")).pack(side="left")

        # --- Kategorie ---
        ttk.Label(outer, text="Kategorie", font=("Segoe UI Semibold", 9)).grid(
            row=4, column=0, sticky="w", pady=(14, 4))
        ttk.Combobox(outer, textvariable=self._cat, width=30,
                     values=[_AUTO] + categories).grid(row=5, column=0, sticky="we")
        ttk.Label(outer, text="Nicht vorhandene Kategorie eintippen – sie wird angelegt.",
                  style="Hint.TLabel").grid(row=6, column=0, sticky="w", pady=(3, 0))

        btns = ttk.Frame(outer)
        btns.grid(row=7, column=0, sticky="e", pady=(18, 0))
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="right", padx=6)
        ttk.Button(btns, text="Übernehmen", style="Accent.TButton",
                   command=self._apply).pack(side="right")

        self._refresh_preview()

    # -- Aktionen -------------------------------------------------
    def _set_color(self, hexv: str) -> None:
        self._color.set(hexv)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        value = self._color.get().strip().lower()
        valid = bool(_HEX_RE.match(value))
        self._preview.configure(bg=value if valid else self.pal["surface"])
        for hexv, sw in self._swatches.items():
            sw.configure(bd=3 if (valid and hexv == value) else 1)

    def _pick(self) -> None:
        cur = self._color.get().strip()
        result = colorchooser.askcolor(
            color=cur if _HEX_RE.match(cur) else None,
            title=f"Farbe – {self._app}", parent=self,
        )
        if result and result[1]:
            self._set_color(result[1])

    def _apply(self) -> None:
        value = self._color.get().strip()
        color = value if _HEX_RE.match(value) else ""
        cat = self._cat.get().strip()
        category = "" if (not cat or cat == _AUTO) else cat
        cb = self._on_apply
        self.destroy()
        cb(color, category)
