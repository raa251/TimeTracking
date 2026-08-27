"""Baut TimeTracker zu einer eigenständigen Windows-.exe (PyInstaller).

    python build.py            -> eine einzelne TimeTracker.exe (dist\TimeTracker.exe)
    python build.py --onedir   -> Ordner dist\TimeTracker\ (startet schneller, weniger
                                  Fehlalarme bei Virenscannern)

Ergebnis liegt in  dist\.  Die .exe braucht auf dem Zielrechner KEIN Python.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ICON = ROOT / "assets" / "TimeTracker.ico"


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller fehlt – installiere es mit:\n    pip install pyinstaller")
        sys.exit(1)


def regenerate_icon() -> None:
    sys.path.insert(0, str(ROOT))
    from timetracker.tray import save_ico

    ICON.parent.mkdir(exist_ok=True)
    save_ico(str(ICON))
    print(f"Icon erzeugt: {ICON}")


def build(onedir: bool) -> None:
    for folder in ("build", "dist"):
        shutil.rmtree(ROOT / folder, ignore_errors=True)
    (ROOT / "TimeTracker.spec").unlink(missing_ok=True)

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onedir" if onedir else "--onefile",
        "--windowed",                       # kein Konsolenfenster (Tray-App)
        "--name", "TimeTracker",
        "--icon", str(ICON),
        "--collect-submodules", "pystray",
        "--hidden-import", "pystray._win32",
        "--hidden-import", "PIL._tkinter_finder",
        "--exclude-module", "numpy",
        "--exclude-module", "pandas",
        "--exclude-module", "pytest",
        "--exclude-module", "setuptools",
        str(ROOT / "run.pyw"),
    ]
    print(">", " ".join(args))
    subprocess.run(args, check=True, cwd=ROOT)

    target = ROOT / "dist" / ("TimeTracker" if onedir else "TimeTracker.exe")
    print("\nFertig.")
    print(f"  {target}")
    if onedir:
        print("  -> ganzen Ordner 'TimeTracker' auf den anderen PC kopieren, darin TimeTracker.exe starten.")
    else:
        print("  -> diese eine Datei auf den anderen PC kopieren und doppelklicken.")


if __name__ == "__main__":
    ensure_pyinstaller()
    regenerate_icon()
    build(onedir="--onedir" in sys.argv)
