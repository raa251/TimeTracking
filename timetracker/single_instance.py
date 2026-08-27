"""Verhindert, dass TimeTracker mehrfach gleichzeitig läuft (Named Mutex).

Wichtig für die verteilte .exe: Autostart + versehentlicher Doppelklick würden
sonst zwei Tracker starten und Zeiten doppelt zählen.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

_ERROR_ALREADY_EXISTS = 183
_MUTEX_NAME = "Global\\TimeTracker_SingleInstance_v1"

_handle = None  # hält den Mutex über die gesamte Prozesslaufzeit am Leben


def acquire() -> bool:
    """True, wenn dies die einzige Instanz ist; False, wenn schon eine läuft."""
    global _handle
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
        handle = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
        if not handle:
            return True  # im Zweifel nicht blockieren
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            return False
        _handle = handle
        return True
    except Exception:  # noqa: BLE001
        return True


def notify_already_running() -> None:
    """Kurzer Hinweis-Dialog. Läuft in einem Thread und blockiert den Start
    höchstens 30 s, damit ein automatischer Doppelstart nicht hängen bleibt."""
    import threading

    def _box() -> None:
        try:
            # MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND
            ctypes.windll.user32.MessageBoxW(
                0, "TimeTracker läuft bereits (Symbol im Infobereich der Taskleiste).",
                "TimeTracker", 0x40 | 0x40000 | 0x10000,
            )
        except Exception:  # noqa: BLE001
            pass

    t = threading.Thread(target=_box, daemon=True)
    t.start()
    t.join(timeout=30)
