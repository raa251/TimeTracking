"""Ableitung von App-Name, Dokument/Datei und Kategorie aus Fensterinfos."""
from __future__ import annotations

import re

from .config import Config

# Dash-Varianten, mit denen Programme Titel-Bestandteile trennen.
_SPLIT_RE = re.compile(r"\s+[‒–—―\-\|]\s+")
_LEAD_RE = re.compile(r"^[\s\*•●○\-]+")

_BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "arc.exe",
             "vivaldi.exe", "opera_gx.exe", "librewolf.exe", "chromium.exe", "waterfox.exe",
             "floorp.exe", "thorium.exe", "zen.exe"}
_EDITORS = {
    "code.exe", "code - insiders.exe", "cursor.exe", "devenv.exe", "pycharm64.exe",
    "idea64.exe", "webstorm64.exe", "rider64.exe", "sublime_text.exe", "notepad++.exe",
    "metaeditor64.exe", "metaeditor.exe",
}

# Editoren, deren Titel "<Datei> — <Projekt> — <App>" lautet (Projekt = vorletztes Feld).
_EDITORS_PROJECT_LAST = {
    "code.exe", "code - insiders.exe", "cursor.exe", "vscodium.exe", "code - oss.exe",
    "windsurf.exe", "devenv.exe", "sublime_text.exe", "fleet.exe", "zed.exe",
}
# JetBrains-IDEs: Titel "<Projekt> – <Pfad/Datei> – <App>" (Projekt = erstes Feld).
_EDITORS_PROJECT_FIRST = {
    "pycharm64.exe", "idea64.exe", "webstorm64.exe", "phpstorm64.exe", "clion64.exe",
    "goland64.exe", "datagrip64.exe", "rubymine64.exe", "rustrover64.exe",
    "studio64.exe", "android studio.exe",
}
# Editoren, deren Titel nur die Datei enthält (kein Projekt) – z. B. MetaEditor:
# "MetaEditor - [MyEA.mq5]". Das Projekt wird über die Datei in den Repos gesucht.
_EDITORS_FILE_ONLY = {"metaeditor64.exe", "metaeditor.exe"}
_APP_LIKE_TAILS = {
    "visual studio code", "vs code", "cursor", "code - oss", "vscodium", "windsurf",
    "microsoft visual studio", "sublime text", "zed", "fleet",
    "metaeditor", "metaeditor 5", "metatrader", "metatrader 5",
}

# Nur ein abschließendes "[branch]" (branch-artig: keine Pfade, keine Leerzeichen)
# wird vom Projektnamen entfernt. Der Branch selbst kommt NICHT aus dem Titel,
# sondern aus .git/HEAD (führte bei manchen Apps zu falschen Werten).
_BRANCH_TRAIL_RE = re.compile(r"\s*\[[A-Za-z][\w.\-]*(?:/[\w.\-]+)*\]\s*$")

# absoluter Windows-Dateipfad im Fenstertitel (z. B. bei MetaEditor, Notepad++)
_WINPATH_RE = re.compile(
    r'[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)+[^\\/:*?"<>|\r\n]+?\.[A-Za-z0-9]{1,8}\b'
)


def path_from_title(title: str) -> str:
    """Extrahiert einen absoluten Windows-Dateipfad aus dem Fenstertitel, falls vorhanden."""
    if not title:
        return ""
    match = _WINPATH_RE.search(title)
    return match.group(0).strip(' "') if match else ""


def strip_branch(text: str) -> str:
    """Entfernt ein abschließendes, branch-artiges ``[main]`` vom Text (Pfade bleiben)."""
    return _BRANCH_TRAIL_RE.sub("", text or "").strip()


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


def is_browser(process: str) -> bool:
    return process.lower() in _BROWSERS


_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)


def domain_from_url(value: str) -> str:
    """``https://www.github.com/x?y``  ->  ``github.com``.  Kein Treffer -> ``""``.

    Für die Adressleisten-Eingabe (Suche, ``chrome://…`` usw.) wird ``""`` geliefert.
    """
    text = (value or "").strip()
    if not text or " " in text.split("/", 1)[0]:
        return ""
    text = _SCHEME_RE.sub("", text)
    host = re.split(r"[/?#\\]", text, 1)[0].strip().lower()
    host = host.split("@")[-1].split(":")[0]           # user:pass@ und :port entfernen
    if host.startswith("www."):
        host = host[4:]
    if "." not in host or host.endswith(".") or len(host) > 253:
        return ""
    if not re.fullmatch(r"[a-z0-9.\-]+", host):
        return ""
    return host


def is_code_editor(process: str, config: Config) -> bool:
    """True für Code-Editoren/IDEs (VS Code, Cursor, JetBrains, MetaEditor …)."""
    key = process.lower()
    extra = {p.lower() for p in config.get("editor_processes", [])}
    return (key in _EDITORS_PROJECT_LAST or key in _EDITORS_PROJECT_FIRST
            or key in _EDITORS_FILE_ONLY or key in extra)


def _debracket(part: str) -> str:
    """Entfernt ein voll umschließendes ``[...]`` / ``(...)`` (MetaEditor-Titel)."""
    part = part.strip()
    if len(part) >= 2 and part[0] in "[(" and part[-1] in "])":
        return part[1:-1].strip()
    return part


def _title_parts(title: str) -> list[str]:
    text = _LEAD_RE.sub("", title or "").strip()
    return [_debracket(p.strip()) for p in _SPLIT_RE.split(text) if p.strip()]


def _file_only_name(title: str, process: str) -> str:
    """Dateiname aus einem "App - [datei]"- bzw. "App : [pfad\\datei]"-Titel (MetaEditor)."""
    brackets = re.findall(r"\[([^\[\]]+)\]", title or "")
    cand = brackets[-1].strip() if brackets else ""
    if not cand:
        parts = _title_parts(title)
        stem = re.sub(r"\.exe$", "", process.lower())
        rest = [p for p in parts if p.lower() not in _APP_LIKE_TAILS and p.lower() != stem]
        cand = rest[-1] if rest else (parts[-1] if parts else "")
    return _LEAD_RE.sub("", re.split(r"[\\/]", cand)[-1]).strip()


def project_name(title: str, process: str) -> str:
    """Projekt-/Ordnername aus einem Editor-Fenstertitel (statt der einzelnen Datei)."""
    if process.lower() in _EDITORS_FILE_ONLY:
        return ""  # kein Projekt im Titel – wird über die Datei in den Repos gesucht
    parts = _title_parts(title)
    if len(parts) <= 1:
        return strip_branch(parts[0]) if parts else ""
    if process.lower() in _EDITORS_PROJECT_FIRST:
        return strip_branch(parts[0])
    while len(parts) > 1 and parts[-1].lower() in _APP_LIKE_TAILS:
        parts.pop()
    return strip_branch(parts[-1] if len(parts) >= 2 else parts[0])


def editor_document(title: str, process: str) -> str:
    """Pfad ab dem Projektordner, z. B. ``TimeTracking/timetracker/reporting.py``.

    Fällt auf ``<Projekt>/<Datei>`` bzw. nur den Dateinamen zurück, je nachdem
    wie viel der Fenstertitel hergibt.
    """
    if process.lower() in _EDITORS_FILE_ONLY:
        return _file_only_name(title, process)
    parts = _title_parts(title)
    if not parts:
        return ""
    if len(parts) == 1:
        return strip_branch(parts[0])
    if process.lower() in _EDITORS_PROJECT_FIRST:
        # "Projekt – src/app/main.py – IDE"
        rel = strip_branch(parts[1]).replace("\\", "/")
        return f"{strip_branch(parts[0])}/{rel}" if len(parts) >= 2 else strip_branch(parts[0])
    while len(parts) > 1 and parts[-1].lower() in _APP_LIKE_TAILS:
        parts.pop()
    file_part = strip_branch(parts[0]).replace("\\", "/")
    if len(parts) >= 2:
        return f"{strip_branch(parts[-1])}/{file_part}"
    return file_part


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


def _matches(process: str, title: str, procs_key: str, patterns_key: str, config: Config) -> bool:
    proc = process.lower()
    if proc in {p.lower() for p in config.get(procs_key, [])}:
        return True
    title_l = title or ""
    for pattern in config.get(patterns_key, []):
        try:
            if re.search(pattern, title_l, re.IGNORECASE):
                return True
        except re.error:
            if pattern.lower() in title_l.lower():
                return True
    return False


def is_private(process: str, title: str, config: Config) -> bool:
    """True, wenn für diese Aktivität keine Details gespeichert werden dürfen."""
    return _matches(process, title, "private_processes", "private_title_patterns", config)


def is_ignored(process: str, title: str, config: Config) -> bool:
    """True für transiente Shell-Fenster (Startmenü, Suche, Alt-Tab, Taskleisten-Overflow).

    Solche Fenster sollen den laufenden Eintrag nicht unterbrechen.
    """
    return _matches(process, title, "ignore_processes", "ignore_title_patterns", config)
