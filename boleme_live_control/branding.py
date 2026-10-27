"""Shared application identity for source runs and packaged Windows builds."""

import ctypes
import sys
from pathlib import Path

from PyQt6.QtGui import QIcon


WINDOWS_APP_ID = "Boleme.LiveControl.Assistant"


def brand_asset(name):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / "assets" / name


def brand_icon():
    return QIcon(str(brand_asset("boleme.ico")))


def configure_taskbar_identity():
    if sys.platform != "win32":
        return
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    set_id = shell32.SetCurrentProcessExplicitAppUserModelID
    set_id.argtypes = [ctypes.c_wchar_p]
    set_id.restype = ctypes.c_long
    result = set_id(WINDOWS_APP_ID)
    if result < 0:
        raise OSError(f"Could not set Windows taskbar identity: HRESULT 0x{result & 0xffffffff:08x}")
