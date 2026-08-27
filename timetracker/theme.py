"""Hell-/Dunkel-Paletten und das ttk-Styling fürs Dashboard."""
from __future__ import annotations

import ctypes
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#eef1f5",
        "surface": "#ffffff",
        "surface_alt": "#f5f7fa",
        "border": "#d6dce5",
        "text": "#1e293b",
        "text_muted": "#64748b",
        "heading_bg": "#eef2f7",
        "grid": "#e8edf3",
        "accent": "#2563eb",
        "bar": "#2563eb",
        "sel_bg": "#2563eb",
        "sel_fg": "#ffffff",
        "bar_label_on": "#ffffff",
        "bar_label_off": "#475569",
        "chart_bg": "#ffffff",
    },
    "dark": {
        "bg": "#15171c",
        "surface": "#1e2128",
        "surface_alt": "#252932",
        "border": "#333a45",
        "text": "#e4e7ec",
        "text_muted": "#98a2b3",
        "heading_bg": "#252932",
        "grid": "#2b303a",
        "accent": "#5b9dff",
        "bar": "#4f8ef7",
        "sel_bg": "#3b6fd4",
        "sel_fg": "#ffffff",
        "bar_label_on": "#ffffff",
        "bar_label_off": "#c7ced9",
        "chart_bg": "#1e2128",
    },
}

# Kategorie -> (Farbe hell, Farbe dunkel)
_CATEGORY_BASE: dict[str, tuple[str, str]] = {
    "Entwicklung": ("#2563eb", "#7aa9ff"),
    "Browser / Recherche": ("#0891b2", "#3bc9db"),
    "Kommunikation": ("#7c3aed", "#b18aff"),
    "Office / Dokumente": ("#16a34a", "#57d98a"),
    "Design / Kreativ": ("#db2777", "#f472b6"),
    "Medien": ("#ea580c", "#fb923c"),
    "Gaming": ("#dc2626", "#f87171"),
    "System / Datei": ("#64748b", "#9aa7b8"),
    "Sonstiges": ("#94a3b8", "#8b95a5"),
    "Abwesenheit": ("#94a3b8", "#7b8494"),
    "Privat": ("#334155", "#aab6c6"),
}


def category_colors(mode: str) -> dict[str, str]:
    idx = 1 if mode == "dark" else 0
    return {name: pair[idx] for name, pair in _CATEGORY_BASE.items()}


def detect_system() -> str:
    """'light' oder 'dark' anhand der Windows-App-Einstellung."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value else "dark"
    except OSError:
        return "light"


def resolve(setting: str | None) -> str:
    """Konfigurationswert ('system' | 'light'/'hell' | 'dark'/'dunkel') -> 'light' | 'dark'."""
    s = (setting or "system").strip().lower()
    if s in ("light", "hell"):
        return "light"
    if s in ("dark", "dunkel"):
        return "dark"
    return detect_system()


def set_titlebar(window: tk.Misc, mode: str) -> None:
    """Färbt die native Windows-Titelleiste hell/dunkel (DWM, ab Win10 20H1)."""
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        value = ctypes.c_int(1 if mode == "dark" else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (neu / alt)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:  # noqa: BLE001
        pass


def apply(style: ttk.Style, root: tk.Misc, mode: str) -> dict[str, str]:
    """Setzt das komplette ttk-Styling für den gewählten Modus. Gibt die Palette zurück."""
    p = PALETTES.get(mode, PALETTES["light"])
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    row_h = tkfont.Font(family="Segoe UI", size=9).metrics("linespace") + 10
    root.configure(bg=p["bg"])

    style.configure(".", background=p["bg"], foreground=p["text"],
                    fieldbackground=p["surface"], bordercolor=p["border"],
                    lightcolor=p["bg"], darkcolor=p["bg"], insertcolor=p["text"])
    style.configure("TFrame", background=p["bg"])
    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("TLabelframe", background=p["bg"], bordercolor=p["border"])
    style.configure("TLabelframe.Label", background=p["bg"], foreground=p["text_muted"])
    style.configure("TButton", background=p["surface_alt"], foreground=p["text"],
                    bordercolor=p["border"], focuscolor=p["accent"])
    style.map("TButton",
              background=[("active", p["border"]), ("pressed", p["border"])],
              foreground=[("disabled", p["text_muted"])])
    style.configure("Accent.TButton", background=p["accent"], foreground="#ffffff")
    style.map("Accent.TButton", background=[("active", p["sel_bg"])])
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=p["bg"], foreground=p["text"],
                        indicatorbackground=p["surface"], indicatorforeground=p["accent"])
        style.map(name,
                  background=[("active", p["bg"])],
                  indicatorbackground=[("selected", p["surface"]), ("pressed", p["surface"])],
                  indicatorforeground=[("selected", p["accent"])])
    style.configure("TCombobox", fieldbackground=p["surface"], background=p["surface_alt"],
                    foreground=p["text"], arrowcolor=p["text"], bordercolor=p["border"])
    style.map("TCombobox",
              fieldbackground=[("readonly", p["surface"])],
              foreground=[("readonly", p["text"])],
              background=[("readonly", p["surface_alt"])])
    style.configure("TSpinbox", fieldbackground=p["surface"], foreground=p["text"],
                    arrowcolor=p["text"], bordercolor=p["border"])
    style.configure("TEntry", fieldbackground=p["surface"], foreground=p["text"],
                    bordercolor=p["border"])
    style.configure("TNotebook", background=p["bg"], bordercolor=p["border"])
    style.configure("TNotebook.Tab", background=p["surface_alt"], foreground=p["text_muted"],
                    padding=(14, 6))
    style.map("TNotebook.Tab",
              background=[("selected", p["bg"])],
              foreground=[("selected", p["text"])])
    style.configure("Treeview", background=p["surface"], fieldbackground=p["surface"],
                    foreground=p["text"], bordercolor=p["border"], rowheight=row_h,
                    font=("Segoe UI", 9))
    style.map("Treeview",
              background=[("selected", p["sel_bg"])],
              foreground=[("selected", p["sel_fg"])])
    style.configure("Treeview.Heading", background=p["heading_bg"], foreground=p["text"],
                    relief="flat", font=("Segoe UI Semibold", 9))
    style.map("Treeview.Heading", background=[("active", p["border"])])
    for sb in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(sb, background=p["surface_alt"], troughcolor=p["bg"],
                        bordercolor=p["border"], arrowcolor=p["text_muted"])
        style.map(sb, background=[("active", p["border"])])

    # Karten
    style.configure("Card.TFrame", background=p["surface"], bordercolor=p["border"],
                    relief="solid", borderwidth=1)
    style.configure("CardValue.TLabel", background=p["surface"], foreground=p["text"],
                    font=("Segoe UI Semibold", 13))
    style.configure("CardCaption.TLabel", background=p["surface"], foreground=p["text_muted"],
                    font=("Segoe UI", 8))
    style.configure("Status.TLabel", background=p["bg"], foreground=p["text_muted"],
                    font=("Segoe UI", 8))
    style.configure("Hint.TLabel", background=p["bg"], foreground=p["text_muted"],
                    font=("Segoe UI", 8))

    # Dropdown-Liste der Comboboxen (klassisches tk-Listbox-Widget)
    root.option_add("*TCombobox*Listbox.background", p["surface"])
    root.option_add("*TCombobox*Listbox.foreground", p["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["sel_bg"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["sel_fg"])
    return p
