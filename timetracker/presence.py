"""Erkennt Anwesenheit ohne Tastatur-/Mauseingabe.

Damit lange Videos und Besprechungen (MS Teams, Zoom …) nicht als „Abwesend"
gezählt werden. Drei Signale:

* **Ton läuft** auf dem Standard-Wiedergabegerät  (Video/Stream)
* **Vollbild-Wiedergabe / Präsentation**          (SHQueryUserNotificationState)
* **Kamera oder Mikrofon in Benutzung**           (CapabilityAccessManager-Registry)

Alles ist defensiv: schlägt eine Prüfung fehl, gilt sie als „kein Signal".
"""
from __future__ import annotations

import ctypes
import logging
import winreg
from ctypes import POINTER, byref, c_float, c_void_p, wintypes

log = logging.getLogger(__name__)

_WINFUNC = ctypes.WINFUNCTYPE
try:
    _HRESULT = ctypes.HRESULT  # type: ignore[attr-defined]
except AttributeError:  # ältere Python-Builds
    _HRESULT = ctypes.c_long


# ---------------------------------------------------------------------------
# 1) Vollbild-Wiedergabe / Präsentationsmodus
# ---------------------------------------------------------------------------
_QUNS_BUSY = 2               # eine Vollbild-App läuft
_QUNS_D3D_FULLSCREEN = 3     # Vollbild-D3D-App (Video/Spiel)
_QUNS_PRESENTATION_MODE = 4  # Präsentationsmodus


def is_fullscreen_or_presenting() -> bool:
    try:
        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(byref(state)) != 0:
            return False
        return state.value in (_QUNS_BUSY, _QUNS_D3D_FULLSCREEN, _QUNS_PRESENTATION_MODE)
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# 2) Kamera / Mikrofon aktiv (Besprechungen)
# ---------------------------------------------------------------------------
_CONSENT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
_CAPS = ("microphone", "webcam")


def _key_in_use(key) -> bool:
    try:
        stop = winreg.QueryValueEx(key, "LastUsedTimeStop")[0]
        start = winreg.QueryValueEx(key, "LastUsedTimeStart")[0]
        if start and not stop:          # gestartet, aber nicht gestoppt -> läuft
            return True
    except OSError:
        pass
    return False


def _capability_in_use(name: str, _depth: int = 0) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{_CONSENT}\\{name}") as root:
            stack = [root]
            # eine Ebene tiefer (App-Pakete) und ggf. "NonPackaged" noch eine
            for _ in range(winreg.QueryInfoKey(root)[0]):
                sub_name = winreg.EnumKey(root, _)
                try:
                    sub = winreg.OpenKey(root, sub_name)
                except OSError:
                    continue
                if _key_in_use(sub):
                    return True
                if sub_name == "NonPackaged":
                    for j in range(winreg.QueryInfoKey(sub)[0]):
                        try:
                            with winreg.OpenKey(sub, winreg.EnumKey(sub, j)) as leaf:
                                if _key_in_use(leaf):
                                    return True
                        except OSError:
                            continue
    except OSError:
        pass
    return False


def is_capture_active() -> bool:
    return any(_capability_in_use(c) for c in _CAPS)


# ---------------------------------------------------------------------------
# 3) Audio-Wiedergabe (Peak-Meter des Standard-Ausgabegeräts) – Core Audio COM
# ---------------------------------------------------------------------------
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
               ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> _GUID:
    g = _GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.create_unicode_buffer(text), byref(g))
    return g


_CLSID_MMDeviceEnumerator = _guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
_IID_IMMDeviceEnumerator = _guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
_IID_IAudioMeterInformation = _guid("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")
_CLSCTX_ALL = 23
_eRender, _eMultimedia = 0, 1


class _EnumVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", _WINFUNC(_HRESULT, c_void_p, c_void_p, c_void_p)),
        ("AddRef", _WINFUNC(ctypes.c_ulong, c_void_p)),
        ("Release", _WINFUNC(ctypes.c_ulong, c_void_p)),
        ("EnumAudioEndpoints", _WINFUNC(_HRESULT, c_void_p, ctypes.c_int, wintypes.DWORD, c_void_p)),
        ("GetDefaultAudioEndpoint", _WINFUNC(_HRESULT, c_void_p, ctypes.c_int, ctypes.c_int,
                                             POINTER(c_void_p))),
    ]


class _DevVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", _WINFUNC(_HRESULT, c_void_p, c_void_p, c_void_p)),
        ("AddRef", _WINFUNC(ctypes.c_ulong, c_void_p)),
        ("Release", _WINFUNC(ctypes.c_ulong, c_void_p)),
        ("Activate", _WINFUNC(_HRESULT, c_void_p, POINTER(_GUID), wintypes.DWORD, c_void_p,
                              POINTER(c_void_p))),
    ]


class _MeterVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", _WINFUNC(_HRESULT, c_void_p, c_void_p, c_void_p)),
        ("AddRef", _WINFUNC(ctypes.c_ulong, c_void_p)),
        ("Release", _WINFUNC(ctypes.c_ulong, c_void_p)),
        ("GetPeakValue", _WINFUNC(_HRESULT, c_void_p, POINTER(c_float))),
    ]


def _vtbl(ptr, vtbl_type):
    return ctypes.cast(ctypes.cast(ptr, POINTER(c_void_p))[0], POINTER(vtbl_type)).contents


def audio_peak() -> float:
    """Aktueller Peak-Pegel (0..1) des Standard-Wiedergabegeräts; -1.0 bei Fehler."""
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)  # S_FALSE, falls bereits initialisiert – egal
    enum = c_void_p()
    if ole32.CoCreateInstance(byref(_CLSID_MMDeviceEnumerator), None, _CLSCTX_ALL,
                              byref(_IID_IMMDeviceEnumerator), byref(enum)) != 0 or not enum.value:
        return -1.0
    dev = meter = None
    try:
        ev = _vtbl(enum, _EnumVtbl)
        dev = c_void_p()
        if ev.GetDefaultAudioEndpoint(enum, _eRender, _eMultimedia, byref(dev)) != 0 or not dev.value:
            return -1.0
        dv = _vtbl(dev, _DevVtbl)
        meter = c_void_p()
        if dv.Activate(dev, byref(_IID_IAudioMeterInformation), _CLSCTX_ALL, None,
                       byref(meter)) != 0 or not meter.value:
            return -1.0
        peak = c_float(0.0)
        if _vtbl(meter, _MeterVtbl).GetPeakValue(meter, byref(peak)) != 0:
            return -1.0
        return float(peak.value)
    except Exception:  # noqa: BLE001
        log.debug("audio_peak fehlgeschlagen", exc_info=True)
        return -1.0
    finally:
        for ptr, vt in ((meter, _MeterVtbl), (dev, _DevVtbl), (enum, _EnumVtbl)):
            if ptr and ptr.value:
                try:
                    _vtbl(ptr, vt).Release(ptr)
                except Exception:  # noqa: BLE001
                    pass


def audio_playing(threshold: float = 0.003) -> bool:
    peak = audio_peak()
    return peak >= threshold


# ---------------------------------------------------------------------------
def user_present() -> tuple[bool, str]:
    """(anwesend?, grund). Reihenfolge: günstigste Prüfung zuerst."""
    if is_fullscreen_or_presenting():
        return True, "Vollbild"
    if is_capture_active():
        return True, "Besprechung"
    if audio_playing():
        return True, "Ton"
    return False, ""
