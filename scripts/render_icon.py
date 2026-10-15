"""Render the brand SVG to the shared runtime PNG and Windows ICO."""

import struct
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "boleme.svg"


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Could not render brand icon")
    return bytes(data)


def main() -> None:
    app = QGuiApplication([])
    renderer = QSvgRenderer(str(SOURCE))
    if not renderer.isValid():
        raise RuntimeError(f"Invalid SVG: {SOURCE}")
    images = [(size, render_png(renderer, size)) for size in (16, 32, 48, 64, 128, 256)]
    (ROOT / "assets" / "boleme.png").write_bytes(images[-1][1])
    offset = 6 + 16 * len(images)
    entries = []
    for size, data in images:
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32,
                                   len(data), offset))
        offset += len(data)
    (ROOT / "assets" / "boleme.ico").write_bytes(
        struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries)
        + b"".join(data for _, data in images)
    )
    app.quit()


if __name__ == "__main__":
    main()
