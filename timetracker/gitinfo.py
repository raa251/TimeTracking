"""Automatische Git-Branch-Erkennung.

Die meisten Editoren schreiben den Branch nicht in den Fenstertitel. Deshalb
werden beim Start (und danach periodisch) die lokalen Git-Repos gesucht und
später über den Ordnernamen (aus dem Fenstertitel) dem passenden Repo
zugeordnet – der Branch kommt dann aus ``.git/HEAD``.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

_COMMON_SUBDIRS = (
    "source/repos", "source", "repos", "dev", "projects", "git", "code", "work",
    "workspace", "src", "Documents", "Desktop", "Projekte", "Programmieren",
)
_SKIP = {
    "node_modules", "appdata", "__pycache__", "venv", ".venv", "env", "library",
    "vendor", "target", "obj", "bin", "packages", "$recycle.bin", "windows",
    "program files", "program files (x86)", "programdata", "system volume information",
    "onedrivetemp", "temp", "tmp", "cache",
}


def _start_dirs(extra_roots) -> list[Path]:
    home = Path.home()
    cands: list[Path] = [home, *(home / s for s in _COMMON_SUBDIRS)]
    for letter in "CDEFGH":
        drive = Path(f"{letter}:\\")
        try:
            if drive.exists():
                cands.append(drive)
        except OSError:
            pass
    cands.extend(Path(r).expanduser() for r in (extra_roots or ()))
    out, seen = [], set()
    for c in cands:
        key = os.path.normcase(str(c))
        if key not in seen:
            seen.add(key)
            try:
                if c.is_dir():
                    out.append(c)
            except OSError:
                pass
    return out


def discover_repos(extra_roots=(), *, max_dirs: int = 12000, max_depth: int = 3,
                   time_budget: float = 8.0) -> dict[str, str]:
    """``{ordnername_lower: absoluter_pfad}`` für gefundene Git-Repos."""
    deadline = time.monotonic() + time_budget
    found: dict[str, str] = {}
    visited: set[str] = set()
    stack: list[tuple[Path, int]] = [(d, 0) for d in _start_dirs(extra_roots)]
    scanned = 0

    while stack and scanned < max_dirs and time.monotonic() < deadline:
        current, depth = stack.pop()
        key = os.path.normcase(str(current))
        if key in visited:
            continue
        visited.add(key)
        scanned += 1
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue

        if any(e.name.lower() == ".git" for e in entries):
            found.setdefault(current.name.lower(), str(current))
            continue  # nicht in ein Repo hinein absteigen
        if depth >= max_depth:
            continue
        for e in entries:
            name = e.name.lower()
            if name in _SKIP or name.startswith("."):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    stack.append((Path(e.path), depth + 1))
            except OSError:
                continue

    log.info("Git-Repos gefunden: %d (%d Ordner geprüft)", len(found), scanned)
    return found


def _git_dir(repo_path: str) -> Path | None:
    dot_git = Path(repo_path) / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():  # Worktree / Submodul: ".git" ist eine Datei
        try:
            line = dot_git.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            return None
        if line.startswith("gitdir:"):
            gd = Path(line.split(":", 1)[1].strip())
            if not gd.is_absolute():
                gd = (Path(repo_path) / gd).resolve()
            return gd
    return None


def head_branch(repo_path: str) -> str:
    """Branch-Name aus ``<repo>/.git/HEAD`` (bei losgelöstem HEAD ein Kurz-SHA)."""
    gd = _git_dir(repo_path)
    if gd is None:
        return ""
    try:
        content = (gd / "HEAD").read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""
    if content.startswith("ref:"):
        return content.split("/", 2)[-1]
    return content[:8]


def find_file_in_repos(filename: str, repo_paths, *, time_budget: float = 3.0) -> list[tuple[str, str]]:
    """Sucht ``filename`` in den angegebenen Repos.

    Rückgabe: ``[(repo_ordner, repo_relativer_pfad)]`` – für Editoren wie MetaEditor,
    deren Titel nur den Dateinamen (kein Projekt, kein Pfad) enthält.
    """
    name = (filename or "").strip().lower()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return []
    deadline = time.monotonic() + time_budget
    hits: list[tuple[str, str]] = []
    for repo in repo_paths:
        if time.monotonic() > deadline or len(hits) >= 4:
            break
        try:
            for dirpath, dirnames, files in os.walk(repo):
                dirnames[:] = [d for d in dirnames
                               if d.lower() not in _SKIP and not d.startswith(".")]
                match = next((f for f in files if f.lower() == name), None)
                if match:
                    rel = os.path.relpath(os.path.join(dirpath, match), repo).replace("\\", "/")
                    hits.append((repo, rel))
                    break
                if time.monotonic() > deadline:
                    break
        except OSError:
            continue
    return hits


def repo_context(path: str) -> tuple[str, str]:
    """``(repo_ordner, branch)`` durch Aufwärts-Suche nach ``.git`` ab ``path``.

    Für Apps, deren Titel den vollen Dateipfad enthält (MetaEditor, Notepad++ …).
    """
    if not path:
        return "", ""
    p = Path(path)
    try:
        if not p.is_dir():
            p = p.parent
    except OSError:
        p = p.parent
    for _ in range(40):
        try:
            if (p / ".git").exists():
                return str(p), head_branch(str(p))
        except OSError:
            pass
        if p.parent == p:
            break
        p = p.parent
    return "", ""
