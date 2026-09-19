from __future__ import annotations

import ctypes
from ctypes import wintypes


DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_MAINWINDOW = 2


def hwnd_of(window) -> int:
    native = getattr(window, "native", None)
    if native is None:
        return 0
    handle = getattr(native, "Handle", None)
    if handle is None:
        return 0
    if hasattr(handle, "ToInt64"):
        return int(handle.ToInt64())
    return int(handle)


def enable_system_backdrop(window) -> bool:
    """Ask DWM for Mica. Do not touch WinForms controls (that hangs off the shown thread)."""
    hwnd = hwnd_of(window)
    if not hwnd:
        return False
    try:
        value = ctypes.c_int(DWMSBT_MAINWINDOW)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(DWMWA_SYSTEMBACKDROP_TYPE),
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        dark = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(DWMWA_USE_IMMERSIVE_DARK_MODE),
            ctypes.byref(dark),
            ctypes.sizeof(dark),
        )
        return True
    except Exception:
        return False
