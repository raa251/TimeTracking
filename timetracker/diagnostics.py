"""Absturz-Diagnose: schreibt native + Python-Stacktraces nach ``crash.log``.

Bei der ``--windowed``-.exe gibt es keine Konsole; ohne diese Datei bleibt ein
harter Absturz (Access Violation in einer DLL, Kill von außen …) unsichtbar.
"""
from __future__ import annotations

import atexit
import datetime as _dt
import faulthandler
import logging
import os
import sys
import threading
import traceback

log = logging.getLogger("timetracker")

_crash_file = None  # bleibt für die Prozesslaufzeit offen (faulthandler braucht das)


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def install(crash_path) -> None:
    """Einmalig aufrufen, so früh wie möglich."""
    global _crash_file
    if _crash_file is not None:
        return
    try:
        _crash_file = open(crash_path, "a", encoding="utf-8", buffering=1)
        _crash_file.write(f"\n===== Start {_stamp()}  pid={os.getpid()}  "
                          f"frozen={getattr(sys, 'frozen', False)} =====\n")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except Exception:  # noqa: BLE001
        _crash_file = None

    def _write(header: str, exc_info) -> None:
        if _crash_file is None:
            return
        try:
            _crash_file.write(f"\n----- {_stamp()}  {header} -----\n")
            traceback.print_exception(*exc_info, file=_crash_file)
            _crash_file.flush()
        except Exception:  # noqa: BLE001
            pass

    def _thread_hook(args):  # threading.excepthook (Py 3.8+)
        name = getattr(args.thread, "name", "?")
        log.error("Unbehandelte Exception im Thread %s", name,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        _write(f"Thread-Exception ({name})",
               (args.exc_type, args.exc_value, args.exc_traceback))

    def _sys_hook(exc_type, exc_value, exc_tb):
        log.critical("Unbehandelte Exception (Hauptthread)",
                     exc_info=(exc_type, exc_value, exc_tb))
        _write("Hauptthread-Exception", (exc_type, exc_value, exc_tb))

    threading.excepthook = _thread_hook
    sys.excepthook = _sys_hook

    @atexit.register
    def _on_exit():
        if _crash_file is not None:
            try:
                _crash_file.write(f"----- {_stamp()}  Prozess endet regulär (atexit) -----\n")
                _crash_file.flush()
            except Exception:  # noqa: BLE001
                pass


def note(message: str) -> None:
    """Freitext in die crash.log (z. B. „Tick 1234 ok")."""
    if _crash_file is not None:
        try:
            _crash_file.write(f"[{_stamp()}] {message}\n")
        except Exception:  # noqa: BLE001
            pass
