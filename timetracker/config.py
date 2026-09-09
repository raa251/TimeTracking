"""Konfiguration, Pfade und Standardwerte."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

APP_NAME = "TimeTracker"

log = logging.getLogger(__name__)


def data_dir() -> Path:
    """Verzeichnis für Datenbank, Konfiguration, Logs und Exporte."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    directory = Path(base) / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "exports").mkdir(exist_ok=True)
    return directory


DATA_DIR = data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "activity.db"
LOG_PATH = DATA_DIR / "timetracker.log"
EXPORT_DIR = DATA_DIR / "exports"


# Anzeigenamen: Prozessname (lowercase) -> lesbarer Name
DEFAULT_APP_NAMES: dict[str, str] = {
    "code.exe": "Visual Studio Code",
    "code - insiders.exe": "VS Code Insiders",
    "cursor.exe": "Cursor",
    "devenv.exe": "Visual Studio",
    "pycharm64.exe": "PyCharm",
    "idea64.exe": "IntelliJ IDEA",
    "webstorm64.exe": "WebStorm",
    "rider64.exe": "Rider",
    "sublime_text.exe": "Sublime Text",
    "notepad++.exe": "Notepad++",
    "notepad.exe": "Editor",
    "windowsterminal.exe": "Windows Terminal",
    "wt.exe": "Windows Terminal",
    "powershell.exe": "PowerShell",
    "pwsh.exe": "PowerShell 7",
    "cmd.exe": "Eingabeaufforderung",
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Mozilla Firefox",
    "brave.exe": "Brave",
    "opera.exe": "Opera",
    "arc.exe": "Arc",
    "explorer.exe": "Windows Explorer",
    "winword.exe": "Word",
    "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint",
    "onenote.exe": "OneNote",
    "outlook.exe": "Outlook",
    "olk.exe": "Outlook (neu)",
    "thunderbird.exe": "Thunderbird",
    "teams.exe": "Microsoft Teams",
    "ms-teams.exe": "Microsoft Teams",
    "slack.exe": "Slack",
    "discord.exe": "Discord",
    "telegram.exe": "Telegram",
    "whatsapp.exe": "WhatsApp",
    "zoom.exe": "Zoom",
    "spotify.exe": "Spotify",
    "vlc.exe": "VLC",
    "mpc-hc64.exe": "MPC-HC",
    "steam.exe": "Steam",
    "epicgameslauncher.exe": "Epic Games",
    "photoshop.exe": "Photoshop",
    "illustrator.exe": "Illustrator",
    "figma.exe": "Figma",
    "blender.exe": "Blender",
    "gimp-2.10.exe": "GIMP",
    "inkscape.exe": "Inkscape",
    "acrobat.exe": "Acrobat",
    "acrord32.exe": "Acrobat Reader",
    "obsidian.exe": "Obsidian",
    "notion.exe": "Notion",
    "metaeditor64.exe": "MetaEditor",
    "metaeditor.exe": "MetaEditor",
    "timetracker.exe": "TimeTracker",
    "terminal64.exe": "MetaTrader 5",
    "terminal.exe": "MetaTrader",
}

# Reihenfolge zählt: die erste passende Regel gewinnt.
DEFAULT_CATEGORIES: list[dict] = [
    {
        "category": "Entwicklung",
        "processes": [
            "code.exe", "code - insiders.exe", "cursor.exe", "devenv.exe",
            "pycharm64.exe", "idea64.exe", "webstorm64.exe", "rider64.exe",
            "sublime_text.exe", "notepad++.exe", "windowsterminal.exe", "wt.exe",
            "powershell.exe", "pwsh.exe", "cmd.exe", "python.exe", "node.exe",
            "docker desktop.exe", "postman.exe",
        ],
        "title_patterns": [],
    },
    {
        "category": "Browser / Recherche",
        "processes": ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "arc.exe"],
        "title_patterns": [],
    },
    {
        "category": "Kommunikation",
        "processes": [
            "teams.exe", "ms-teams.exe", "slack.exe", "discord.exe", "outlook.exe",
            "olk.exe", "thunderbird.exe", "telegram.exe", "whatsapp.exe", "zoom.exe",
        ],
        "title_patterns": [],
    },
    {
        "category": "Office / Dokumente",
        "processes": [
            "winword.exe", "excel.exe", "powerpnt.exe", "onenote.exe", "acrobat.exe",
            "acrord32.exe", "obsidian.exe", "notion.exe",
        ],
        "title_patterns": [],
    },
    {
        "category": "Design / Kreativ",
        "processes": [
            "photoshop.exe", "illustrator.exe", "figma.exe", "blender.exe",
            "gimp-2.10.exe", "inkscape.exe",
        ],
        "title_patterns": [],
    },
    {
        "category": "Medien",
        "processes": ["spotify.exe", "vlc.exe", "wmplayer.exe", "music.ui.exe", "mpc-hc64.exe"],
        "title_patterns": ["youtube", "netflix", "twitch"],
    },
    {
        "category": "Gaming",
        "processes": ["steam.exe", "epicgameslauncher.exe", "battle.net.exe", "riotclientux.exe"],
        "title_patterns": [],
    },
    {
        "category": "System / Datei",
        "processes": ["explorer.exe", "taskmgr.exe", "systemsettings.exe", "mmc.exe", "regedit.exe",
                      "timetracker.exe"],
        "title_patterns": [],
    },
]

# Grobe Produktivitäts-Wertung je Kategorie: 1 = produktiv, 0 = neutral, -1 = ablenkend
DEFAULT_PRODUCTIVITY: dict[str, int] = {
    "Entwicklung": 1,
    "Office / Dokumente": 1,
    "Design / Kreativ": 1,
    "Kommunikation": 0,
    "Browser / Recherche": 0,
    "System / Datei": 0,
    "Medien": -1,
    "Gaming": -1,
    "Sonstiges": 0,
}

DEFAULTS: dict = {
    "poll_interval_seconds": 3,
    "idle_threshold_seconds": 120,
    "retention_days": 90,
    "min_segment_seconds": 1,
    "track_titles": True,
    "autostart": False,
    # Kein "Abwesend", solange ein Video läuft (Ton), Vollbild-Wiedergabe aktiv ist
    # oder eine Besprechung läuft (Kamera/Mikrofon in Benutzung).
    "keep_active_on_media": True,
    # Für Browser die Domain (github.com, youtube.com …) aus der Adressleiste erfassen
    # statt nur den Seitentitel. Nutzt UI Automation; bei Bedarf abschaltbar.
    "track_browser_domain": True,
    # Standardansicht (= "Detailansicht"-Haken aus): Editoren pro Projekt zusammenfassen.
    "collapse_editor_projects": True,
    "editor_processes": [],   # zusätzliche Editoren/IDEs (ergänzt die eingebaute Liste)
    # Optionale zusätzliche Ordner, die beim automatischen Git-Repo-Scan
    # (für die Branch-Anzeige) mit durchsucht werden. Normalerweise nicht nötig.
    "project_roots": [],
    # Datenschutz: für diese Prozesse/Titel werden keine Details gespeichert.
    "private_processes": ["keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe"],
    "private_title_patterns": ["passwort", "password", "banking", "\\bTAN\\b"],
    # Transiente Shell-Fenster (Startmenü, Suche, Alt-Tab, Taskleisten-Overflow):
    # der aktuelle Eintrag bleibt bestehen, statt für 1-2 s zu wechseln.
    "ignore_processes": [
        "SearchHost.exe", "SearchApp.exe", "StartMenuExperienceHost.exe",
        "ShellExperienceHost.exe", "TextInputHost.exe", "LockApp.exe",
    ],
    "ignore_title_patterns": ["Überlauffenster der Taskleiste", "Task-Umschalten", "Task Switching"],
    "app_names": {},          # überschreibt/ergänzt DEFAULT_APP_NAMES
    "app_colors": {},         # {"Visual Studio Code": "#2563eb"} – eigene Farbe je App
    "app_categories": {},     # {"Visual Studio Code": "Meine Kategorie"} – Kategorie je App
    "categories": [],         # ersetzt DEFAULT_CATEGORIES, wenn nicht leer
    "productivity": {},       # überschreibt/ergänzt DEFAULT_PRODUCTIVITY
    "deleted_categories": [], # ausgeblendete Kategorien (auch Standardkategorien)
    "idle_goal_hours": 6.0,   # Tagesziel "aktive Zeit" für die Fortschrittsanzeige
    "theme": "system",        # "system" | "light" | "dark"
    "developer_mode": False,  # zeigt zusätzlich die Git-Branch-Spalte
}


class Config:
    """Lädt/merged ``config.json`` mit den Defaults und schreibt Änderungen zurück."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else CONFIG_PATH
        self.data: dict = json.loads(json.dumps(DEFAULTS))  # deep copy
        self.load()

    # -- Zugriff --------------------------------------------------------------
    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def __getitem__(self, key: str):
        return self.data[key]

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()

    # -- persistente App-Namen ---------------------------------------------
    @property
    def app_names(self) -> dict[str, str]:
        merged = dict(DEFAULT_APP_NAMES)
        merged.update({k.lower(): v for k, v in self.data.get("app_names", {}).items()})
        return merged

    @property
    def app_colors(self) -> dict[str, str]:
        return dict(self.data.get("app_colors", {}))

    @property
    def app_categories(self) -> dict[str, str]:
        return dict(self.data.get("app_categories", {}))

    @property
    def deleted_categories(self) -> set[str]:
        return {c for c in self.data.get("deleted_categories", []) if c}

    @property
    def categories(self) -> list[dict]:
        base = self.data["categories"] or DEFAULT_CATEGORIES
        gone = self.deleted_categories
        return [r for r in base if r.get("category") not in gone] if gone else base

    @property
    def productivity(self) -> dict[str, int]:
        merged = dict(DEFAULT_PRODUCTIVITY)
        merged.update(self.data.get("productivity", {}))
        for c in self.deleted_categories:
            merged.pop(c, None)
        return merged

    # -- I/O ---------------------------------------------------------------
    def load(self) -> None:
        if not self.path.exists():
            self.save()
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            for key, value in loaded.items():
                self.data[key] = value
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("config.json konnte nicht gelesen werden: %s", exc)

    def save(self) -> None:
        try:
            self.path.write_text(
                json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            log.warning("config.json konnte nicht geschrieben werden: %s", exc)
