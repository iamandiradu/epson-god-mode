"""Pages printed through the installed printer driver (Windows / macOS / CUPS).

Raw ESC/P2 raster is head-specific (the epson_escp2 colour pattern targets
the XP-200/XP-205), so anything that has to look right on *every* model is
drawn with Qt and handed to the system print queue: the Epson driver knows its
own head, colour order and dot sizes.

* colour test page: CMYK and RGB blocks, gradients, fine lines and text;
* single-colour purge pages: solid pages of one ink (pure C, M, Y or K) to
  flush a weak colour without a cleaning, so no ink goes to the waste pads.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

PURGE_COLORS = {  # pure RGB values the Epson drivers map to a single ink
    "Yellow": (255, 255, 0),
    "Cyan": (0, 255, 255),
    "Magenta": (255, 0, 255),
    "Black": (0, 0, 0),
}


def _app():
    """QPrinter/QPainter need a GUI application object (offscreen on headless Linux)."""
    import os
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication([sys.argv[0]])
    return app


def driver_queues() -> list[str]:
    _app()
    from PySide6.QtPrintSupport import QPrinterInfo
    return [p.printerName() for p in QPrinterInfo.availablePrinters()]


def pick_driver_queue(model: str) -> Optional[str]:
    """The installed queue matching ``model`` (e.g. 'EPSON L310 Series')."""
    import re
    want = re.sub(r"[^a-z0-9]", "", (model or "").lower().replace("series", ""))
    queues = driver_queues()
    for q in queues:
        if want and want in re.sub(r"[^a-z0-9]", "", q.lower()):
            return q
    epson = [q for q in queues if "epson" in q.lower()]
    return epson[0] if len(epson) == 1 else None


def _printer(target: str, title: str):
    from PySide6.QtGui import QPageLayout, QPageSize
    from PySide6.QtCore import QMarginsF
    from PySide6.QtPrintSupport import QPrinter
    p = QPrinter(QPrinter.HighResolution)
    p.setDocName(title)
    if target.startswith("pdf:"):
        p.setOutputFormat(QPrinter.PdfFormat)
        p.setOutputFileName(target[4:])
    else:
        p.setPrinterName(target)
        if not p.isValid():
            raise RuntimeError(f"print queue '{target}' not found")
    p.setColorMode(QPrinter.Color)
    p.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(8, 8, 8, 8),
                                QPageLayout.Millimeter))
    return p


def print_color_test(target: str, model: str = "") -> str:
    """CMYK/RGB blocks, gradients, fine lines and text on one A4 page."""
    _app()
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
    printer = _printer(target, "Epson God Mode colour test")
    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError(f"could not start printing on '{target}'")
    try:
        r = printer.pageLayout().paintRectPixels(printer.resolution())
        w, h = r.width(), r.height()
        u = w / 100.0  # 1 % of page width
        painter.setFont(QFont("Arial", 14, QFont.Bold))
        painter.drawText(QRectF(0, 0, w, 6 * u), Qt.AlignLeft | Qt.AlignVCenter,
                         f"Epson God Mode — colour test {model}")
        painter.setFont(QFont("Arial", 8))
        painter.drawText(QRectF(0, 0, w, 6 * u), Qt.AlignRight | Qt.AlignVCenter,
                         _dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
        y = 8 * u
        blocks = [("C", (0, 255, 255)), ("M", (255, 0, 255)), ("Y", (255, 255, 0)), ("K", (0, 0, 0)),
                  ("R", (255, 0, 0)), ("G", (0, 255, 0)), ("B", (0, 0, 255))]
        bw = w / len(blocks)
        painter.setFont(QFont("Arial", 10, QFont.Bold))
        for i, (name, rgb) in enumerate(blocks):
            rect = QRectF(i * bw + u * 0.5, y, bw - u, 18 * u)
            painter.fillRect(rect, QColor(*rgb))
            painter.setPen(QColor(255, 255, 255) if name in "KB" else QColor(0, 0, 0))
            painter.drawText(rect, Qt.AlignCenter, name)
        y += 21 * u
        painter.setPen(QColor(0, 0, 0))
        for name, rgb in blocks[:4] + [("Grey", (0, 0, 0))]:
            grad = QLinearGradient(0, 0, w, 0)
            grad.setColorAt(0, QColor(255, 255, 255))
            grad.setColorAt(1, QColor(*rgb))
            painter.fillRect(QRectF(10 * u, y, w - 10 * u, 6 * u), grad)
            painter.drawText(QRectF(0, y, 9 * u, 6 * u), Qt.AlignVCenter | Qt.AlignLeft, name)
            y += 8 * u
        # fine lines: horizontal and vertical, in each ink (shows banding / misalignment)
        y += 2 * u
        for k, rgb in enumerate([(0, 0, 0), (0, 255, 255), (255, 0, 255), (255, 255, 0)]):
            pen = QPen(QColor(*rgb))
            pen.setWidthF(max(1.0, printer.resolution() / 300.0))
            painter.setPen(pen)
            x0 = k * w / 4
            for j in range(0, 40):
                xx = x0 + u + j * (w / 4 - 2 * u) / 40
                painter.drawLine(int(xx), int(y), int(xx), int(y + 18 * u))
            for j in range(0, 18):
                yy = y + 20 * u + j * u
                painter.drawLine(int(x0 + u), int(yy), int(x0 + w / 4 - u), int(yy))
        y += 40 * u
        painter.setPen(QColor(0, 0, 0))
        painter.setFont(QFont("Arial", 9))
        painter.drawText(QRectF(0, y, w, h - y), Qt.TextWordWrap,
                         "Solid blocks should be even, without white lines. Gradients should be smooth. "
                         "Fine lines should be straight and continuous. A missing or striped colour: print a "
                         "nozzle check; for a single weak colour, use Purge one colour before any cleaning.")
    finally:
        painter.end()
    return f"colour test page sent to '{target}' through the printer driver"


def print_purge(target: str, color: str, pages: int = 2) -> str:
    """``pages`` solid pages of one pure ink."""
    if color not in PURGE_COLORS:
        raise ValueError(f"colour must be one of {', '.join(PURGE_COLORS)}")
    if not 1 <= pages <= 5:
        raise ValueError("pages must be between 1 and 5")
    _app()
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QPainter
    printer = _printer(target, f"Epson God Mode purge {color}")
    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError(f"could not start printing on '{target}'")
    try:
        for i in range(pages):
            if i:
                printer.newPage()
            r = printer.pageLayout().paintRectPixels(printer.resolution())
            painter.fillRect(QRectF(0, 0, r.width(), r.height()), QColor(*PURGE_COLORS[color]))
    finally:
        painter.end()
    return f"{pages} solid {color.lower()} page(s) sent to '{target}' through the printer driver"
