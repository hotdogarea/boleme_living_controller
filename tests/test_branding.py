import ctypes
import os
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QApplication

from boleme_live_control.branding import (
    WINDOWS_APP_ID, brand_asset, brand_icon, configure_taskbar_identity,
)


class BrandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_icon_has_real_rasters_for_taskbar_and_high_dpi(self):
        icon = brand_icon()
        self.assertFalse(icon.isNull())
        self.assertTrue({QSize(size, size) for size in (16, 32, 48, 64, 128, 256)}
                        .issubset(set(icon.availableSizes())))
        data = brand_asset("boleme.ico").read_bytes()
        self.assertEqual(struct.unpack_from("<HHH", data), (0, 1, 6))
        for size in (16, 32, 48, 64):
            image = icon.pixmap(size, size).toImage()
            white_pixels = sum(image.pixelColor(x, y).red() > 230
                               and image.pixelColor(x, y).green() > 230
                               and image.pixelColor(x, y).alpha() > 230
                               for x in range(size) for y in range(size))
            self.assertGreater(white_pixels, size / 4)

    def test_svg_wordmark_has_outlines_not_font_dependent_text(self):
        svg = brand_asset("boleme.svg").read_text(encoding="utf-8")
        self.assertIn("播了么", svg)
        self.assertIn("<path", svg)
        self.assertNotIn("<text", svg)

    def test_packaged_asset_root_and_build_include_runtime_icon(self):
        with patch.object(sys, "_MEIPASS", "bundle-test", create=True):
            self.assertEqual(brand_asset("boleme.ico"), Path("bundle-test/assets/boleme.ico"))
        build = (Path(__file__).resolve().parents[1] / "build.ps1").read_text(encoding="utf-8")
        self.assertIn('--add-data "${icon};assets"', build)
        self.assertIn('--icon $icon', build)

    def test_identity_and_icon_are_configured_before_first_window(self):
        from boleme_live_control.app import main

        with patch("boleme_live_control.app.configure_taskbar_identity") as identity, \
                patch("boleme_live_control.app.QApplication") as application, \
                patch("boleme_live_control.app.data_dir"), \
                patch("boleme_live_control.app.QLockFile") as lock, \
                patch("boleme_live_control.app.QMessageBox.warning"):
            application.side_effect = lambda _args: (
                self.assertTrue(identity.called) or application.return_value)
            lock.return_value.tryLock.return_value = False
            main()
            application.return_value.setWindowIcon.assert_called_once()
            self.assertFalse(application.return_value.setWindowIcon.call_args.args[0].isNull())

    @unittest.skipUnless(sys.platform == "win32", "Windows taskbar identity")
    def test_windows_process_identity_is_not_python(self):
        configure_taskbar_identity()
        shell32 = ctypes.WinDLL("shell32")
        get_id = shell32.GetCurrentProcessExplicitAppUserModelID
        get_id.argtypes = [ctypes.POINTER(ctypes.c_wchar_p)]
        get_id.restype = ctypes.c_long
        identity = ctypes.c_wchar_p()
        self.assertEqual(get_id(ctypes.byref(identity)), 0)
        try:
            self.assertEqual(identity.value, WINDOWS_APP_ID)
        finally:
            free = ctypes.WinDLL("ole32").CoTaskMemFree
            free.argtypes = [ctypes.c_void_p]
            free.restype = None
            free(ctypes.cast(identity, ctypes.c_void_p))


if __name__ == "__main__":
    unittest.main()
