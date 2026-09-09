"""Liest die URL aus der Adressleiste des aktiven Browserfensters – via UI Automation.

Reines ctypes (kein comtypes/pywin32), analog zu ``presence.py``. Alles defensiv:
schlägt etwas fehl, kommt ``""`` zurück und der Aufrufer nutzt weiter den Fenstertitel.
"""
from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import POINTER, byref, c_int, c_long, c_ubyte, c_ushort, c_void_p, wintypes

log = logging.getLogger(__name__)

_CLSID_CUIAutomation = "{FF48DBA4-60EF-4201-AA87-54103EEF594E}"
_IID_IUIAutomation = "{30CBE57D-D9D0-452A-AB13-7AC5AC4825EE}"
_CLSCTX_INPROC_SERVER = 1
_COINIT_MULTITHREADED = 0x0

_UIA_ControlTypePropertyId = 30003
_UIA_ValueValuePropertyId = 30045
_UIA_EditControlTypeId = 50004
_TreeScope_Descendants = 4
_VT_I4 = 3
_VT_BSTR = 8

# vtable-Indizes (IUnknown belegt 0,1,2)
_IUIA_ElementFromHandle = 6
_IUIA_CreatePropertyCondition = 23
_IEL_FindFirst = 5
_IEL_GetCurrentPropertyValue = 10
_RELEASE = 2

_ptr_size = ctypes.sizeof(c_void_p)


class _GUID(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD),
                ("d", c_ubyte * 8)]


def _guid(text: str) -> _GUID:
    g = _GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.create_unicode_buffer(text), byref(g))
    return g


class _VARIANT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("lVal", c_long), ("ptr", c_void_p), ("_pad", c_ubyte * 16)]
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                ("u", _U)]


def _vcall(ptr, index, restype, argtypes, *args):
    vtbl = ctypes.cast(ptr, POINTER(c_void_p)).contents.value
    slot = ctypes.cast(vtbl + index * _ptr_size, POINTER(c_void_p)).contents.value
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(slot)(ptr, *args)


def _release(ptr) -> None:
    if ptr and getattr(ptr, "value", ptr):
        try:
            _vcall(ptr, _RELEASE, ctypes.c_ulong, [])
        except Exception:  # noqa: BLE001
            pass


_tls = threading.local()


def _automation():
    """IUIAutomation dieses Threads (einmalig erstellt); False, wenn nicht verfügbar."""
    cached = getattr(_tls, "uia", None)
    if cached is not None:
        return cached
    ole = ctypes.windll.ole32
    try:
        ole.CoInitializeEx(None, _COINIT_MULTITHREADED)  # S_OK/S_FALSE/RPC_E_CHANGED_MODE – egal
        p = c_void_p()
        hr = ole.CoCreateInstance(byref(_guid(_CLSID_CUIAutomation)), None,
                                  _CLSCTX_INPROC_SERVER, byref(_guid(_IID_IUIAutomation)), byref(p))
        _tls.uia = p if (hr == 0 and p.value) else False
    except Exception:  # noqa: BLE001
        _tls.uia = False
    if _tls.uia is False:
        log.debug("UI Automation nicht verfügbar")
    return _tls.uia


def active_url(hwnd: int) -> str:
    """URL/Text der Adressleiste des Browserfensters ``hwnd`` – oder ``""``."""
    if not hwnd:
        return ""
    uia = _automation()
    if not uia:
        return ""

    element = cond = found = None
    try:
        element = c_void_p()
        if _vcall(uia, _IUIA_ElementFromHandle, c_long, [c_void_p, POINTER(c_void_p)],
                  hwnd, byref(element)) != 0 or not element.value:
            return ""

        val = _VARIANT()
        val.vt = _VT_I4
        val.u.lVal = _UIA_EditControlTypeId
        cond = c_void_p()
        if _vcall(uia, _IUIA_CreatePropertyCondition, c_long, [c_int, _VARIANT, POINTER(c_void_p)],
                  _UIA_ControlTypePropertyId, val, byref(cond)) != 0 or not cond.value:
            return ""

        found = c_void_p()
        if _vcall(element, _IEL_FindFirst, c_long, [c_int, c_void_p, POINTER(c_void_p)],
                  _TreeScope_Descendants, cond, byref(found)) != 0 or not found.value:
            return ""

        out = _VARIANT()
        if _vcall(found, _IEL_GetCurrentPropertyValue, c_long, [c_int, POINTER(_VARIANT)],
                  _UIA_ValueValuePropertyId, byref(out)) != 0:
            return ""
        try:
            if out.vt == _VT_BSTR and out.u.ptr:
                return ctypes.wstring_at(out.u.ptr).strip()
            return ""
        finally:
            try:
                ctypes.windll.oleaut32.VariantClear(byref(out))
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        log.debug("active_url fehlgeschlagen", exc_info=True)
        return ""
    finally:
        _release(found)
        _release(cond)
        _release(element)
