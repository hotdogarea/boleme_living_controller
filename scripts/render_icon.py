"""Render the brand SVG to the shared runtime PNG and Windows ICO."""

import argparse
import struct
from pathlib import Path
from xml.etree import ElementTree

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QImage, QPainter, QPainterPath
from PyQt6.QtSvg import QSvgGenerator, QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "boleme.svg"


def write_wordmark() -> None:
    family = "Noto Sans SC"
    if family not in QFontDatabase.families():
        raise RuntimeError("Noto Sans SC is required to regenerate the outlined wordmark")
    font = QFont(family)
    font.setPixelSize(100)
    font.setWeight(QFont.Weight.Bold)
    generator = QSvgGenerator()
    generator.setFileName(str(SOURCE))
    generator.setViewBox(QRect(0, 0, 256, 256))
    generator.setTitle("播了么")
    generator.setDescription("Outlined brand lettering; no runtime font dependency")
    painter = QPainter(generator)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#24796d"))
    painter.drawRoundedRect(QRectF(4, 4, 248, 248), 42, 42)
    painter.setBrush(QColor("#ffffff"))
    for text, box in (("播", QRectF(80, 24, 96, 98)), ("了么", QRectF(30, 138, 196, 92))):
        path = QPainterPath()
        path.addText(0, 0, font, text)
        path.setFillRule(Qt.FillRule.WindingFill)
        bounds = path.boundingRect()
        scale = min(box.width() / bounds.width(), box.height() / bounds.height())
        painter.save()
        painter.translate(box.center())
        painter.scale(scale, scale)
        painter.translate(-bounds.center())
        painter.drawPath(path)
        painter.restore()
    painter.end()
    tree = ElementTree.parse(SOURCE)
    for element in tree.iter():
        for key in tuple(element.attrib):
            if key.startswith("font-"):
                del element.attrib[key]
    ElementTree.register_namespace("", "http://www.w3.org/2000/svg")
    ElementTree.indent(tree, space="  ")
    tree.write(SOURCE, encoding="utf-8", xml_declaration=True)


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-wordmark", action="store_true",
                        help="Regenerate the outlined Chinese brand SVG before rendering")
    args = parser.parse_args()
    app = QGuiApplication([])
    if args.refresh_wordmark:
        write_wordmark()
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
