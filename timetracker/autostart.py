"""Windows-Autostart über den HKCU\\...\\Run-Schlüssel (nur für den aktuellen Nutzer)."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "TimeTracker"


def _launch_command() -> str:
    """Kommandozeile, die den Tray-Client ohne Konsolenfenster startet."""
    if getattr(sys, "frozen", False):
        # gebündelte .exe (PyInstaller) – direkt starten
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw) if pythonw.exists() else sys.executable
    launcher = Path(__file__).resolve().parent.parent / "run.pyw"
    return f'"{exe}" "{launcher}"'


def is_enabled() -> bool:
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.warning("Autostart-Status nicht lesbar: %s", exc)
        return False


def enable() -> bool:
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
        log.info("Autostart aktiviert: %s", _launch_command())
        return True
    except OSError as exc:
        log.error("Autostart konnte nicht aktiviert werden: %s", exc)
        return False


def disable() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
        log.info("Autostart deaktiviert")
        return True
    except FileNotFoundError:
        return True
    except OSError as exc:
        log.error("Autostart konnte nicht deaktiviert werden: %s", exc)
        return False


def toggle() -> bool:
    if is_enabled():
        disable()
    else:
        enable()
    return is_enabled()
