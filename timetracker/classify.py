"""Ableitung von App-Name, Dokument/Datei und Kategorie aus Fensterinfos."""
from __future__ import annotations

import re

from .config import Config

# Dash-Varianten, mit denen Programme Titel-Bestandteile trennen.
_SPLIT_RE = re.compile(r"\s+[‒–—―\-\|]\s+")
_LEAD_RE = re.compile(r"^[\s\*•●○\-]+")

_BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "arc.exe"}
_EDITORS = {
    "code.exe", "code - insiders.exe", "cursor.exe", "devenv.exe", "pycharm64.exe",
    "idea64.exe", "webstorm64.exe", "rider64.exe", "sublime_text.exe", "notepad++.exe",
}


def friendly_app_name(process: str, config: Config) -> str:
    """Lesbarer Programmname, z. B. ``Code.exe`` -> ``Visual Studio Code``."""
    if not process:
        return "Unbekannt"
    key = process.lower()
    names = config.app_names
    if key in names:
        return names[key]
    stem = re.sub(r"\.exe$", "", process, flags=re.IGNORECASE)
    stem = stem.replace("_", " ").replace("-", " ").strip()
    return stem[:1].upper() + stem[1:] if stem else process


def parse_document(title: str, process: str) -> str:
    """Versucht, aus dem Fenstertitel die konkrete Datei/Seite herauszulösen."""
    if not title:
        return ""
    text = _LEAD_RE.sub("", title).strip()
    parts = [p.strip() for p in _SPLIT_RE.split(text) if p.strip()]
    if len(parts) <= 1:
        return text

    key = process.lower()
    if key in _BROWSERS:
        # "Seitentitel - Google Chrome"  ->  "Seitentitel"
        return " - ".join(parts[:-1]).strip()
    if key in _EDITORS:
        # "● main.py - projekt - Visual Studio Code"  ->  "main.py"
        return parts[0]
    if key in {"winword.exe", "excel.exe", "powerpnt.exe"}:
        return parts[0]
    if key == "explorer.exe":
        return parts[-1]

    # generisch: letzten Teil verwerfen, wenn er wie ein Programmname aussieht
    tail = parts[-1].lower()
    stem = re.sub(r"\.exe$", "", key)
    if tail == stem or tail in {"microsoft edge", "google chrome", "mozilla firefox"}:
        return " - ".join(parts[:-1]).strip()
    return text


def categorize(process: str, title: str, config: Config) -> str:
    """Ordnet eine Aktivität einer Kategorie zu (erste passende Regel gewinnt)."""
    proc = process.lower()
    title_l = (title or "").lower()
    for rule in config.categories:
        procs = {p.lower() for p in rule.get("processes", [])}
        if proc and proc in procs:
            return rule["category"]
        for pattern in rule.get("title_patterns", []):
            try:
                if re.search(pattern, title_l, re.IGNORECASE):
                    return rule["category"]
            except re.error:
                if pattern.lower() in title_l:
                    return rule["category"]
    return "Sonstiges"


def is_private(process: str, title: str, config: Config) -> bool:
    """True, wenn für diese Aktivität keine Details gespeichert werden dürfen."""
    proc = process.lower()
    if proc in {p.lower() for p in config.get("private_processes", [])}:
        return True
    title_l = (title or "")
    for pattern in config.get("private_title_patterns", []):
        try:
            if re.search(pattern, title_l, re.IGNORECASE):
                return True
        except re.error:
            if pattern.lower() in title_l.lower():
                return True
    return False
