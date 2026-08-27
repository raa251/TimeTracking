"""Dünne ctypes-Wrapper um die Win32-APIs, die für das Tracking gebraucht werden.

Bewusst ohne pywin32/psutil, damit die Installation nur ``pystray`` benötigt.
Alle Funktionen sind defensiv: schlägt ein Aufruf fehl, wird ein neutraler
Wert zurückgegeben statt einer Exception.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- Konstanten ----------------------------------------------------------------
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DESKTOP_READOBJECTS = 0x0001

# --- Funktionsprototypen ------------------------------------------------------
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []

user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]

user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

user32.GetLastInputInfo.restype = wintypes.BOOL

user32.OpenInputDesktop.restype = wintypes.HANDLE
user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

user32.CloseDesktop.restype = wintypes.BOOL
user32.CloseDesktop.argtypes = [wintypes.HANDLE]

kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]

kernel32.GetTickCount64.restype = ctypes.c_ulonglong
kernel32.GetTickCount64.argtypes = []


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def get_idle_seconds() -> float:
    """Sekunden seit der letzten Tastatur-/Mauseingabe des Nutzers."""
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    # dwTime ist ein 32-Bit-Tickwert (GetTickCount); Überlauf nach ~49 Tagen.
    now = kernel32.GetTickCount64() & 0xFFFFFFFF
    elapsed = (now - info.dwTime) & 0xFFFFFFFF
    return max(0.0, elapsed / 1000.0)


def is_workstation_locked() -> bool:
    """True, wenn der Sperrbildschirm/Secure Desktop aktiv ist.

    ``OpenInputDesktop`` schlägt fehl, solange die Sitzung gesperrt ist.
    """
    hdesk = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
    if not hdesk:
        return True
    user32.CloseDesktop(hdesk)
    return False


def _process_path(pid: int) -> str:
    if not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def get_active_window() -> dict | None:
    """Infos zum aktuell aktiven Vordergrundfenster oder ``None``.

    Rückgabe-Keys: ``hwnd``, ``pid``, ``title``, ``exe_path``, ``process``.
    """
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    length = user32.GetWindowTextLengthW(hwnd)
    title = ""
    if length > 0:
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe_path = _process_path(pid.value)
    process = exe_path.rsplit("\\", 1)[-1] if exe_path else ""

    return {
        "hwnd": int(hwnd),
        "pid": int(pid.value),
        "title": title,
        "exe_path": exe_path,
        "process": process,
    }
