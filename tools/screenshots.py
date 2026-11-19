"""Regenerate docs/screenshots/*.png from the app running against the simulator.

    QT_QPA_PLATFORM=offscreen python tools/screenshots.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "2")  # crisp images for the docs
os.environ["HOME"] = "/home/user"  # neutral backup path in the log
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "screenshots"

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)  # no exec() loop here
        time.sleep(0.02)


def main() -> None:
    app = QApplication([sys.argv[0]])
    app.setStyle("Fusion")
    app.setFont(QFont("DejaVu Sans", 9))
    from egm.gui.app import MainWindow
    from egm.operations import PrinterSession
    OUT.mkdir(parents=True, exist_ok=True)
    win = MainWindow()
    win.resize(1100, 720)
    win.show()
    pump(1.5)

    def shot(name: str, wait: float = 1.0) -> None:
        pump(wait)
        win.grab().save(str(OUT / f"{name}.png"))
        print("saved", name)

    cp = win.pages["Printer"]
    cp.devices.setEditText("sim:L3111")
    cp.model.setCurrentText("L3111")
    shot("01-printer")

    s = PrinterSession.connect("sim:L3111", None)
    from egm.modeldb import load
    s.model = load().get("L3111")  # what the GUI does when the hint belongs to the detected family
    win.set_session(s)
    pump(4)
    order = list(win.pages)

    def page(title: str) -> None:
        win.nav.setCurrentRow(order.index(title))

    page("Status"); shot("02-status", 3)
    page("Waste ink pads")
    wp = win.pages["Waste ink pads"]
    wp.check()
    shot("03-waste", 3)
    from egm.gui.widgets import ConfirmDialog
    dlg = ConfirmDialog(
        "Reset waste ink counters",
        f"This writes {len(s.family.waste_reset)} EEPROM cells on your <b>{s.model.name}</b>. "
        "A backup of those cells is saved first and every write is read back.",
        s.model.name,
        ["The waste ink pads were replaced/cleaned, or an external waste tank is fitted.",
         "The printer is idle (not printing, cleaning or flushing ink).",
         "I understand this is at my own risk."], win)
    dlg.show()
    pump(0.8)
    dlg.grab().save(str(OUT / "03b-reset-confirm.png"))
    dlg.close()
    page("Maintenance")
    win.start_operation("Head cleaning", "head_cleaning")
    win.activity.op.started -= 28
    win.activity.op.saw_work = True
    from egm.activity import Snapshot
    win._snaps.append(Snapshot("cleaning", "Cleaning"))
    shot("04-maintenance", 1.5)
    win.finish_operation("done")
    win.activity.op = None
    page("Adjustments") if "Adjustments" in order else None
    shot("05-adjustments", 1.5)
    page("Counters & errors") if "Counters & errors" in order else None
    cnt = win.pages.get("Counters & errors")
    if cnt and hasattr(cnt, "refresh"):
        cnt.refresh()
    shot("06-counters", 3)
    page("EEPROM")
    ep = win.pages["EEPROM"]
    if hasattr(ep, "dump"):
        ep.dump()
    shot("07-eeprom", 3)
    page("Troubleshooting")
    tp = win.pages["Troubleshooting"]
    if hasattr(tp, "search"):
        try:
            tp.search.setText("yellow missing")
        except Exception:
            pass
    pump(1)
    for row in range(tp.list.count()):
        if "Purge" in tp.list.item(row).text():
            tp.list.setCurrentRow(row)
    pump(1)
    for w in QApplication.topLevelWidgets():
        if w.isVisible() and w is not win:
            print("popup:", type(w).__name__, w.objectName(), w.geometry())
            w.hide()
    shot("08-troubleshooting", 0.5)
    page("Model database")
    shot("09-models", 1.5)
    win.close()


if __name__ == "__main__":
    main()
