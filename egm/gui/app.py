"""Main window."""
from __future__ import annotations

import datetime as _dt
import json
import sys
from importlib.resources import files
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QCompleter, QDateEdit, QFileDialog,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSplitter,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout,
                               QWidget)

from .. import APP_NAME, __version__
from .. import backup as backup_mod
from .. import printjobs as pj
from ..modeldb import COVERAGE_LABELS, load as load_db
from ..operations import PrinterSession
from ..transport import discover_all
from ..activity import ActivityTracker, fmt_duration
from .widgets import Badge, ConfirmDialog, LevelBar, StatusStrip, hline
from .workers import Runner

DISCLAIMER = (
    "Resetting the waste ink counter does not empty the pads. Before resetting, replace or "
    "clean the waste ink pads, or fit an external waste ink tank, otherwise ink can leak out of "
    "the printer. This software is not affiliated with Seiko Epson Corporation. Use at your own risk."
)


def mono() -> QFont:
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    return f


class Page(QWidget):
    title = ""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win

    @property
    def session(self) -> Optional[PrinterSession]:
        return self.win.session

    def on_session_changed(self) -> None:
        pass

    def run(self, fn, *args, done=None, label: str = "", **kw):
        self.win.run(fn, *args, done=done, label=label, **kw)


# --------------------------------------------------------------------------- #
#  Connect
# --------------------------------------------------------------------------- #
class ConnectPage(Page):
    title = "Printer"

    def __init__(self, win):
        super().__init__(win)
        db = load_db()
        lay = QVBoxLayout(self)

        dev = QGroupBox("1. Connection")
        g = QGridLayout(dev)
        self.devices = QComboBox()
        self.devices.setEditable(True)
        self.devices.setToolTip("usb (auto), usb:<path>, a printer IP, or sim:<MODEL> for the simulator")
        scan = QPushButton("Scan")
        scan.clicked.connect(self.scan)
        self.network = QCheckBox("include network (SNMP)")
        g.addWidget(QLabel("Device:"), 0, 0)
        g.addWidget(self.devices, 0, 1)
        g.addWidget(scan, 0, 2)
        g.addWidget(self.network, 1, 1)
        lay.addWidget(dev)

        mdl = QGroupBox("2. Model")
        f = QFormLayout(mdl)
        self.auto = QCheckBox("Detect automatically from the printer")
        self.auto.setChecked(True)
        self.model = QComboBox()
        self.model.setEditable(True)
        featured = [m.name for m in db.featured()]
        others = [n for n in db.names() if n not in featured]
        self.model.addItems(featured)
        self.model.insertSeparator(len(featured))
        self.model.addItems(others)
        self.model.setCurrentText("L3111")
        comp = QCompleter(featured + others)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.model.setCompleter(comp)
        self.model.currentTextChanged.connect(self.show_model)
        f.addRow(self.auto)
        f.addRow("Model (used when detection fails, or to override):", self.model)
        self.model_info = QLabel()
        self.model_info.setWordWrap(True)
        f.addRow(self.model_info)
        lay.addWidget(mdl)

        opt = QGroupBox("3. Safety")
        v = QVBoxLayout(opt)
        self.dry = QCheckBox("Dry run — never write to the printer, only log what would be written")
        v.addWidget(self.dry)
        lbl = QLabel(DISCLAIMER)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #b71c1c;")
        v.addWidget(lbl)
        lay.addWidget(opt)

        btns = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setDefault(True)
        self.connect_btn.clicked.connect(self.connect_printer)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.win.disconnect)
        btns.addStretch(1)
        btns.addWidget(self.disconnect_btn)
        btns.addWidget(self.connect_btn)
        lay.addLayout(btns)
        lay.addStretch(1)
        self.devices.addItem("usb", "usb")
        self.show_model(self.model.currentText())
        QTimer.singleShot(200, self.scan)

    def show_model(self, name: str) -> None:
        m = load_db().get(name)
        if not m:
            self.model_info.setText("<i>Unknown model</i>")
            return
        ver = {"egm": "verified on hardware by this project", "community": "verified by the community"}.get(m.verified or "", "not yet verified on hardware")
        alias = f"<br>Re-badge of {m.alias_of}; uses its data." if m.alias_of else ""
        self.model_info.setText(
            f"<b>{m.title}</b> — reports as <code>{m.model_string}</code><br>"
            f"Family <b>{m.family.name}</b> ({len(m.family.models)} models) · coverage <b>{m.coverage}</b>: "
            f"{COVERAGE_LABELS[m.coverage]}<br>Status: {ver}{alias}")

    def scan(self) -> None:
        net = self.network.isChecked()

        def done(eps):
            cur = self.devices.currentText()
            self.devices.clear()
            self.devices.addItem("usb  (first Epson USB printer)", "usb")
            for e in eps:
                self.devices.addItem(f"{e.label}  [{e.model_string}]" if e.model_string else e.label, e.address)
            idx = next((i for i in range(self.devices.count()) if self.devices.itemData(i) == cur), -1)
            if idx >= 0:
                self.devices.setCurrentIndex(idx)
            usb = [e for e in eps if e.kind == "usb"]
            self.win.log(f"Scan: {len(usb)} USB, {len([e for e in eps if e.kind == 'snmp'])} network printer(s)")
            if usb:
                self.devices.setCurrentIndex(1)
        self.run(discover_all, True, net, done=done, label="Scanning")

    def connect_printer(self) -> None:
        addr = self.devices.currentData() or self.devices.currentText().strip()
        model = None if self.auto.isChecked() else self.model.currentText().strip()
        hint = self.model.currentText().strip()
        dry = self.dry.isChecked()

        def do():
            try:
                return PrinterSession.connect(addr, model, dry_run=dry)
            except Exception:
                if model is None and hint:
                    # detection failed: fall back to the selected model
                    return PrinterSession.connect(addr, hint, dry_run=dry)
                raise

        def done(s: PrinterSession):
            if model is None and not s.detected:
                self.win.log(f"Could not detect the model; using the selected one ({s.model.name}).")
            elif s.detected:
                # L3110 and L3111 report the same model string: keep the user's
                # name when it belongs to the detected family.
                hm = load_db().get(hint)
                if hm and hm.family is s.family and hm is not s.model:
                    s.model = hm
            self.model.setCurrentText(s.model.name)
            self.win.set_session(s)
        self.run(do, done=done, label="Connecting")


# --------------------------------------------------------------------------- #
#  Status
# --------------------------------------------------------------------------- #
class StatusPage(Page):
    title = "Status"

    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        self.header = QLabel("Not connected")
        self.header.setTextFormat(Qt.RichText)
        self.header.setWordWrap(True)
        lay.addWidget(self.header)
        self.state = QLabel()
        self.state.setStyleSheet("font-size: 15px; font-weight: 600;")
        lay.addWidget(self.state)
        self.ink_box = QGroupBox("Ink levels (as reported by the printer)")
        self.ink_lay = QVBoxLayout(self.ink_box)
        lay.addWidget(self.ink_box)
        self.waste_box = QGroupBox("Waste ink pad counters")
        self.waste_lay = QVBoxLayout(self.waste_box)
        lay.addWidget(self.waste_box)
        self.extra = QLabel()
        self.extra.setWordWrap(True)
        lay.addWidget(self.extra)
        b = QPushButton("Refresh")
        b.clicked.connect(self.refresh)
        lay.addWidget(b, alignment=Qt.AlignRight)
        lay.addStretch(1)

    def on_session_changed(self) -> None:
        self.refresh()

    def _clear(self, layout) -> None:
        while layout.count():
            w = layout.takeAt(0).widget()
            if w:
                w.deleteLater()

    def refresh(self) -> None:
        s = self.session
        if not s:
            self.header.setText("Not connected")
            return

        def work():
            info = s.info()
            st = s.status()
            waste, werr = [], None
            if s.family.waste_counters and s.family.read_key:
                try:
                    waste = s.waste_levels()
                except Exception as exc:  # noqa: BLE001
                    werr = str(exc)
            return info, st, waste, werr

        def done(res):
            info, st, waste, werr = res
            self.header.setText(
                f"<b>{info.model}</b> · family {info.family} · firmware {info.firmware or '?'} · "
                f"serial {info.serial or '?'}<br><small>{info.link} — "
                f"{'auto-detected' if info.detected else 'model set manually'}</small>")
            self.state.setText(f"{st.state}" + (f" — ERROR: {st.error}" if st.error else ""))
            self.state.setStyleSheet("font-size: 15px; font-weight: 600; color: %s;" % ("#c62828" if st.error else "#2e7d32"))
            self._clear(self.ink_lay)
            if not st.inks:
                self.ink_lay.addWidget(QLabel("No ink information in the status block."))
            for ink in st.inks:
                bar = LevelBar(ink.color)
                bar.set_value(ink.level if 0 <= ink.level <= 100 else None, ink.level_text)
                self.ink_lay.addWidget(bar)
            self._clear(self.waste_lay)
            if werr:
                lbl = QLabel(f"Could not read the waste counters: {werr}")
                lbl.setWordWrap(True)
                self.waste_lay.addWidget(lbl)
            for w in waste:
                bar = LevelBar(w.name, invert=True)
                bar.set_value(w.percent, w.text)
                self.waste_lay.addWidget(bar)
            notes = []
            if st.warnings:
                notes.append("Warnings: " + "; ".join(st.warnings))
            if st.maintenance_boxes:
                notes.append("Maintenance box: " + ", ".join(st.maintenance_boxes))
            if st.paper_counts:
                notes.append("Paper counts: " + ", ".join(f"{k} {v}" for k, v in st.paper_counts.items()))
            self.extra.setText("<br>".join(notes))
        self.run(work, done=done, label="Reading status")


# --------------------------------------------------------------------------- #
#  Waste ink reset
# --------------------------------------------------------------------------- #
class WastePage(Page):
    title = "Waste ink pads"

    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        intro = QLabel(
            "<h3>Waste ink pad counter</h3>The printer estimates how much ink went into its absorbent pads. "
            "When the estimate reaches 100% it stops with “service required” (red lights blinking alternately on "
            "L-series). A reset sets the estimate back to zero; it does <b>not</b> clean the pads.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.bars = QVBoxLayout()
        lay.addLayout(self.bars)
        self.cover = QLabel()
        self.cover.setWordWrap(True)
        lay.addWidget(self.cover)
        b = QHBoxLayout()
        self.check_btn = QPushButton("Check counters")
        self.check_btn.clicked.connect(self.check)
        self.reset_btn = QPushButton("Reset counters…")
        self.reset_btn.setStyleSheet("QPushButton { font-weight: 600; }")
        self.reset_btn.clicked.connect(self.reset)
        self.rw_btn = QPushButton("Temporary reset (rw)…")
        self.rw_btn.setToolTip("Firmware 'rw' command keyed by the serial number. Works on some firmwares that lock "
                               "EEPROM writes; the effect may be temporary.")
        self.rw_btn.clicked.connect(self.temp_reset)
        b.addWidget(self.check_btn)
        b.addStretch(1)
        b.addWidget(self.rw_btn)
        b.addWidget(self.reset_btn)
        lay.addLayout(b)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setFont(mono())
        lay.addWidget(self.result, 1)

    def on_session_changed(self) -> None:
        s = self.session
        if not s:
            return
        f = s.family
        txt = f"Family <b>{f.name}</b>: {COVERAGE_LABELS[f.coverage]}."
        if f.waste_reset:
            txt += "<br>Reset writes: " + ", ".join(f"{a:#06x}={v:#04x}" for a, v in f.waste_reset.items())
        self.cover.setText(txt)
        self.reset_btn.setEnabled(bool(f.waste_reset) and (f.can_write or s.dry_run))
        self.check()

    def check(self) -> None:
        s = self.session
        if not s:
            return

        def done(levels):
            while self.bars.count():
                w = self.bars.takeAt(0).widget()
                if w:
                    w.deleteLater()
            for w in levels:
                bar = LevelBar(w.name, invert=True)
                bar.set_value(w.percent, w.text)
                self.bars.addWidget(bar)
            self.result.appendPlainText(_dt.datetime.now().strftime("%H:%M:%S ") +
                                        " | ".join(f"#{w.index + 1} {w.text}" for w in levels))
        self.run(s.waste_levels, done=done, label="Reading counters")

    def reset(self) -> None:
        s = self.session
        if not s:
            return
        dlg = ConfirmDialog(
            "Reset waste ink counters",
            f"This writes {len(s.family.waste_reset)} EEPROM cells on your <b>{s.model.name}</b>. "
            "A backup of those cells is saved first and every write is read back.",
            s.model.name,
            ["The waste ink pads were replaced/cleaned, or an external waste tank is fitted.",
             "The printer is idle (not printing, cleaning or flushing ink).",
             "I understand this is at my own risk."], self)
        if not dlg.exec():
            return

        def done(r):
            self.result.appendPlainText(f"Backup: {r.backup_path}")
            for m in r.messages:
                self.result.appendPlainText(m)
            self.result.appendPlainText("RESULT: " + ("OK" if r.ok else "FAILED — restore the backup from the EEPROM page"))
            if r.ok and not r.dry_run:
                QMessageBox.information(self, "Reset done", "Counters reset and verified.\n\nTurn the printer off and on again.")
            self.check()
        self.run(s.reset_waste, acknowledge_pads_replaced=True, done=done, label="Resetting")

    def temp_reset(self) -> None:
        s = self.session
        if not s:
            return
        if QMessageBox.question(self, "Temporary reset", "Send the firmware 'rw' command for this printer's serial number?") != QMessageBox.Yes:
            return
        self.run(s.temporary_reset, done=lambda r: self.result.appendPlainText(f"rw: {r}"), label="Sending rw")


# --------------------------------------------------------------------------- #
#  Maintenance
# --------------------------------------------------------------------------- #
class MaintenancePage(Page):
    title = "Maintenance"

    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)

        ctrl = QGroupBox("Service commands (control channel, no paper needed)")
        g = QHBoxLayout(ctrl)
        self.clean_combo = QComboBox()
        self.clean_btn = QPushButton("Run")
        self.clean_btn.clicked.connect(self.run_clean)
        g.addWidget(QLabel("Cleaning / ink charge:"))
        g.addWidget(self.clean_combo, 1)
        g.addWidget(self.clean_btn)
        lay.addWidget(ctrl)

        jobs = QGroupBox("Print jobs (sent straight to the connected printer — paper may be required)")
        f = QFormLayout(jobs)
        self.queue = QComboBox()
        self.queue.setEditable(True)
        self.queue.setToolTip("Normally 'This printer (direct)'. Alternatives: a Windows/macOS print queue, "
                              "an IP[:port], or file:<path> to save the job instead of printing it.")
        rq = QPushButton("Refresh")
        rq.clicked.connect(self.refresh_queues)
        f.addRow("Send via:", self._row(self.queue, rq))
        for label, key in [("Nozzle check pattern", "nozzle"), ("Head cleaning (driver-style)", "clean"),
                           ("Power cleaning", "power"),
                           ("Colour test page (through the Epson driver)", "color"),
                           ("Purge one colour… (solid pages, no waste ink)", "purge"),
                           ("Service cleaning (strongest level, as print job)", "svc_clean"),
                           ("Initial ink charge (uses a lot of ink!)", "charge"),
                           ("Ink discharge (F2 sequence — L3110/L3150 generation)", "discharge"),
                           ("Release stuck job (printer paused mid-print / whining)", "release")]:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, k=key: self.print_job(k))
            f.addRow(b)
        save = QPushButton("Save selected job as .prn instead…")
        save.clicked.connect(self.save_job)
        self.save_kind = QComboBox()
        self.save_kind.addItems(["nozzle", "clean", "power", "svc_clean", "charge", "discharge"])
        f.addRow(self._row(self.save_kind, save))
        lay.addWidget(jobs)

        extra = QGroupBox("Model-specific EEPROM operations (from the model database)")
        v = QVBoxLayout(extra)
        self.extra_list = QListWidget()
        v.addWidget(self.extra_list)
        eb = QPushButton("Run selected…")
        eb.clicked.connect(self.run_extra)
        v.addWidget(eb, alignment=Qt.AlignRight)
        lay.addWidget(extra, 1)

        date = QGroupBox("First-use date (First TI received time)")
        h = QHBoxLayout(date)
        self.date = QDateEdit(_dt.date.today())
        self.date.setCalendarPopup(True)
        db = QPushButton("Write date…")
        db.clicked.connect(self.write_date)
        h.addWidget(self.date)
        h.addWidget(db)
        h.addStretch(1)
        lay.addWidget(date)
        self.refresh_queues()

    @staticmethod
    def _row(*ws):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        for x in ws:
            h.addWidget(x)
        return w

    def refresh_queues(self) -> None:
        """'This printer (direct)' first; installed queues only as alternatives."""
        self.queue.clear()
        s = self.session
        if s is None or getattr(s.link, "print_raw", None) is not None:
            self.queue.addItem("This printer (direct)", "direct")
        for q in pj.list_queues():
            self.queue.addItem(f"Print queue: {q['name']}", q["name"])
        self.queue.setCurrentIndex(0)

    def on_session_changed(self) -> None:
        s = self.session
        self.clean_combo.clear()
        self.extra_list.clear()
        if not s:
            return
        for o in s.cleaning_options():
            self.clean_combo.addItem(o["name"])
        self.clean_btn.setEnabled(self.clean_combo.count() > 0)
        for op in s.extra_operations():
            it = QListWidgetItem(op["name"] + "  — " + ", ".join(f"{int(a):#06x}={v:#04x}" for a, v in op["write"].items()))
            self.extra_list.addItem(it)
        if not s.extra_operations():
            self.extra_list.addItem("(none for this family)")
        self.refresh_queues()

    def run_clean(self) -> None:
        s = self.session
        if not s:
            return
        i = self.clean_combo.currentIndex()
        name = self.clean_combo.currentText()
        if "Charg" in name and QMessageBox.warning(self, "Ink charge", "An ink charge pumps a lot of ink into the waste pads. Continue?",
                                                   QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        if not self._confirm_if_busy(name):
            return
        target = self.queue.currentData() or self.queue.currentText().strip() or "direct"
        opt = s.cleaning_options()[i] if 0 <= i < len(s.cleaning_options()) else {}
        level = (opt.get("data") or [0])[0]
        kind = "ink_charge" if opt.get("kind") == "charging" else ("power_cleaning" if level >= 4 else "head_cleaning")
        self.win.start_operation(name, kind)

        def done(r):
            self.win.log(r)
            if ": done" not in r:
                self.win.finish_operation("not confirmed")
            elif not (self.win.activity.last and self.win.activity.last.working):
                self.win.finish_operation("done")
            # else: still working (e.g. a long ink charge) -- the status poller
            # finishes the operation when the printer reports ready

        def failed(msg, tb):
            self.win.finish_operation("failed")
            self.win.log(f"ERROR ({name}): {msg}")
            QMessageBox.critical(self, name, msg)
        self.win.busy_label.setText(name + "…")
        self.win.runner.submit(s.run_cleaning, i, target, on_done=done, on_error=failed)

    def _confirm_if_busy(self, what: str) -> bool:
        if not self.win.printer_working():
            return True
        return QMessageBox.question(
            self, "Printer is busy",
            f"The printer still looks busy ({self.win.strip.title.text()}).\n\n"
            f"Start “{what}” anyway? Running maintenance back to back wastes ink.") == QMessageBox.Yes

    def _job(self, key: str) -> Optional[bytes]:
        s = self.session
        fam = s.family if s else None
        if key == "nozzle":
            return pj.nozzle_check()
        if key == "release":
            return pj.release_stuck_job()
        if key == "clean":
            return pj.head_cleaning()
        if key == "power":
            return pj.head_cleaning(power=True)
        if key == "color":
            return pj.color_test_pattern()
        if fam is None:
            QMessageBox.warning(self, "Not connected", "Connect (or select a model) first: factory jobs use the model's key.")
            return None
        try:
            if key == "svc_clean":
                return pj.service_cleaning_job(fam)
            if key == "charge":
                return pj.ink_charge_job(fam)
        except ValueError as exc:
            QMessageBox.warning(self, "Not available for this model", str(exc))
            return None
        if key == "discharge":
            jd = pj.service_jobs()["ink_discharge_f2"]
            if fam.name not in jd["families"]:
                QMessageBox.warning(self, "Not available", f"The discharge script is only known for families {', '.join(jd['families'])}.")
                return None
            if QMessageBox.warning(self, "Ink discharge", "Experimental: replays the L3110 factory discharge sequence. "
                                   "Only run it when you know you need it. Continue?",
                                   QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return None
            return pj.scripted_job(fam, "ink_discharge_f2")
        return None

    def _driver_target(self) -> Optional[str]:
        """Installed print queue for driver-rendered pages (colour test, purge)."""
        from .. import driverprint as dp
        sel = self.queue.currentData()
        if sel and sel != "direct":
            return sel
        s = self.session
        model = (s.model.model_string or s.model.name) if s else self.win.pages["Printer"].model.currentText()
        q = dp.pick_driver_queue(model)
        if q:
            return q
        queues = dp.driver_queues()
        if not queues:
            QMessageBox.warning(self, "No printer driver",
                                "These pages are printed through the Epson printer driver, and no print queue is "
                                "installed. Install the Epson driver for your printer, then try again.")
            return None
        from PySide6.QtWidgets import QInputDialog
        q, ok = QInputDialog.getItem(self, "Choose the printer", "Print through which installed printer?", queues, 0, False)
        return q if ok else None

    def driver_page(self, key: str) -> None:
        from .. import driverprint as dp
        target = self._driver_target()
        if not target:
            return
        if key == "purge":
            from PySide6.QtWidgets import QInputDialog
            color, ok = QInputDialog.getItem(self, "Purge one colour",
                                             "Which colour is weak? Solid pages of it use only that ink and nothing "
                                             "goes to the waste pads.", list(dp.PURGE_COLORS), 0, False)
            if not ok:
                return
            pages, ok = QInputDialog.getInt(self, "Purge one colour", "Number of pages (2–3 is usually enough):", 2, 1, 5)
            if not ok:
                return
            name, kind = f"Purge {color.lower()}", "print"
        else:
            name, kind = "Colour test page", "print"
        if not self._confirm_if_busy(name):
            return
        s = self.session
        if s and hasattr(s.link, "suspend"):
            s.link.suspend()  # the spooler needs the USB port; the app reconnects by itself
        try:
            if key == "purge":
                res = dp.print_purge(target, color, pages)
            else:
                res = dp.print_color_test(target, s.model.name if s else "")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, name, str(exc))
            return
        self.win.log(res)
        if s:
            self.win.start_operation(name, kind)

    def _service_option(self, key: str) -> int:
        """Index of the matching cleaning option (charge, or strongest service cleaning)."""
        opts = self.session.cleaning_options() if self.session else []
        if key == "charge":
            idx = [i for i, o in enumerate(opts) if o.get("kind") == "charging"]
        else:
            idx = [i for i, o in enumerate(opts) if o.get("kind") == "cleaning" and o.get("type") == "service"]
            idx.sort(key=lambda i: (opts[i].get("data") or [0])[0])
        return idx[-1] if key != "charge" and idx else (idx[0] if idx else -1)

    def print_job(self, key: str) -> None:
        if key in ("color", "purge"):
            self.driver_page(key)
            return
        if key in ("charge", "svc_clean") and self.session is not None:
            # control channel first (the way the printer accepts it most often),
            # then the factory print job, with the result confirmed either way
            i = self._service_option(key)
            if i < 0:
                QMessageBox.warning(self, "Not available for this model", "No factory code is known for this model.")
                return
            self.clean_combo.setCurrentIndex(i)
            self.run_clean()
            return
        job = self._job(key)
        if job is None:
            return
        target = self.queue.currentData() or self.queue.currentText().strip() or "direct"
        s = self.session
        if s is None:
            if target == "direct":
                QMessageBox.warning(self, "Not connected", "Connect to the printer first, or choose a print queue / file: target.")
                return
            self.run(pj.send, job, target, done=lambda r: self.win.log(r), label="Sending job")
            return
        names = {"nozzle": ("Nozzle check", "nozzle_check"), "clean": ("Head cleaning", "head_cleaning"),
                 "power": ("Power cleaning", "power_cleaning"), "color": ("Colour test page", "print"),
                 "svc_clean": ("Service cleaning", "head_cleaning"), "charge": ("Ink charge", "ink_charge"),
                 "discharge": ("Ink discharge", "ink_discharge")}
        if key in names and not target.startswith("file:"):
            if not self._confirm_if_busy(names[key][0]):
                return
            self.win.start_operation(*names[key])
        self.run(s.print_job, job, target, done=lambda r: self.win.log(r), label="Sending job")

    def save_job(self) -> None:
        job = self._job(self.save_kind.currentText())
        if job is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save print job", f"{self.save_kind.currentText()}.prn", "Print files (*.prn)")
        if path:
            Path(path).write_bytes(job)
            self.win.log(f"Saved {len(job)} bytes to {path}")

    def run_extra(self) -> None:
        s = self.session
        if not s or not s.extra_operations():
            return
        i = self.extra_list.currentRow()
        if i < 0:
            return
        op = s.extra_operations()[i]
        if QMessageBox.question(self, "Run operation", f"Run “{op['name']}”? A backup is taken first.") != QMessageBox.Yes:
            return
        self.run(s.run_extra_operation, i, done=lambda r: self.win.log(f"{op['name']}: {'OK' if r.ok else 'FAILED'} (backup {r.backup_path})"), label=op["name"])

    def write_date(self) -> None:
        s = self.session
        if not s:
            return
        d = self.date.date().toPython()
        if QMessageBox.question(self, "Write date", f"Set the first-use date to {d.isoformat()}?") != QMessageBox.Yes:
            return
        self.run(s.set_first_ti_date, d, done=lambda r: self.win.log(f"First TI date: {'OK' if r.ok else 'FAILED'}"), label="Writing date")


# --------------------------------------------------------------------------- #
#  Counters & errors
# --------------------------------------------------------------------------- #
class CountersPage(Page):
    title = "Counters & errors"

    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Item", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 2)
        b = QPushButton("Read counters")
        b.clicked.connect(self.refresh)
        lay.addWidget(b, alignment=Qt.AlignRight)

        look = QGroupBox("Error code lookup")
        h = QVBoxLayout(look)
        r = QHBoxLayout()
        self.code = QLineEdit()
        self.code.setPlaceholderText("e.g. 0x7919 or 31001")
        self.kind = QComboBox()
        self.kind.addItems(["PRINTER", "SCANNER", "GENERAL"])
        go = QPushButton("Look up")
        go.clicked.connect(self.lookup)
        self.code.returnPressed.connect(self.lookup)
        r.addWidget(self.code)
        r.addWidget(self.kind)
        r.addWidget(go)
        h.addLayout(r)
        self.answer = QTextBrowser()
        h.addWidget(self.answer)
        lay.addWidget(look, 1)

    def on_session_changed(self) -> None:
        self.table.setRowCount(0)
        if self.session:
            self.refresh()

    def refresh(self) -> None:
        s = self.session
        if not s:
            return

        def done(items: dict):
            self.table.setRowCount(0)
            for k, v in items.items():
                r = self.table.rowCount()
                self.table.insertRow(r)
                self.table.setItem(r, 0, QTableWidgetItem(k))
                self.table.setItem(r, 1, QTableWidgetItem(", ".join(map(str, v)) if isinstance(v, list) else str(v)))
        self.run(s.counters, done=done, label="Reading counters")

    def lookup(self) -> None:
        txt = self.code.text().strip()
        try:
            code = int(txt, 0) if txt.lower().startswith("0x") else int(txt, 16) if any(c in "abcdefABCDEF" for c in txt) else int(txt)
        except ValueError:
            self.answer.setHtml("<i>Enter a number (hex with 0x, or decimal).</i>")
            return
        db = load_db()
        fams = [self.session.family] if self.session else []
        fams += [db.get("L3110").family] if db.get("L3110") else []
        hits = []
        for fam in fams:
            for c in {code, code & 0xFFFF}:
                d = db.fatal_text(fam, self.kind.currentText(), c)
                if d and d not in hits:
                    hits.append(d)
        if not hits:
            # search every table
            for tname, table in db.fatal_codes.items():
                for k, v in table.items():
                    if v.get("type") == self.kind.currentText() and int(k, 0) == code:
                        hits.append({"code": k, **v, "table": tname})
        if not hits:
            self.answer.setHtml(f"<i>No description for {code:#06x} ({self.kind.currentText()}).</i>")
            return
        self.answer.setHtml("".join(f"<p><b>{h['code']}</b> ({h.get('table', h['type'])}): {h['text']}</p>" for h in hits[:8]))


# --------------------------------------------------------------------------- #
#  EEPROM
# --------------------------------------------------------------------------- #
class EepromPage(Page):
    title = "EEPROM"

    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.start = QLineEdit("0x000")
        self.end = QLineEdit("0x0FF")
        for w in (self.start, self.end):
            w.setMaximumWidth(90)
        dump = QPushButton("Read range")
        dump.clicked.connect(self.dump)
        top.addWidget(QLabel("From"))
        top.addWidget(self.start)
        top.addWidget(QLabel("to"))
        top.addWidget(self.end)
        top.addWidget(dump)
        top.addStretch(1)
        bk = QPushButton("Backup known cells")
        bk.clicked.connect(lambda: self.backup(False))
        bf = QPushButton("Full backup")
        bf.clicked.connect(lambda: self.backup(True))
        rs = QPushButton("Restore backup…")
        rs.clicked.connect(self.restore)
        top.addWidget(bk)
        top.addWidget(bf)
        top.addWidget(rs)
        lay.addLayout(top)
        split = QSplitter(Qt.Vertical)
        self.hex = QPlainTextEdit()
        self.hex.setReadOnly(True)
        self.hex.setFont(mono())
        self.hex.setLineWrapMode(QPlainTextEdit.NoWrap)
        split.addWidget(self.hex)

        tools = QWidget()
        tl = QVBoxLayout(tools)
        rw = QGroupBox("Read / write single cells")
        g = QHBoxLayout(rw)
        self.addr = QLineEdit()
        self.addr.setPlaceholderText("address, e.g. 0x30")
        self.val = QLineEdit()
        self.val.setPlaceholderText("value, e.g. 0x00")
        rb = QPushButton("Read")
        rb.clicked.connect(self.read_one)
        wb = QPushButton("Write…")
        wb.clicked.connect(self.write_one)
        for w in (self.addr, self.val, rb, wb):
            g.addWidget(w)
        tl.addWidget(rw)

        diff = QGroupBox("EEPROM diff (discover where an adjustment is stored)")
        d = QVBoxLayout(diff)
        info = QLabel("1) Take snapshot A. 2) Change one setting on the printer (or with another tool). "
                      "3) Take snapshot B. The cells that changed are listed — share them so the model database can grow.")
        info.setWordWrap(True)
        d.addWidget(info)
        h = QHBoxLayout()
        sa = QPushButton("Snapshot A")
        sa.clicked.connect(lambda: self.snapshot("A"))
        sb = QPushButton("Snapshot B + compare")
        sb.clicked.connect(lambda: self.snapshot("B"))
        h.addWidget(sa)
        h.addWidget(sb)
        h.addStretch(1)
        d.addLayout(h)
        tl.addWidget(diff)
        split.addWidget(tools)
        lay.addWidget(split, 1)
        self.snaps: dict[str, dict[int, int]] = {}

    def on_session_changed(self) -> None:
        s = self.session
        if s:
            r = s.family.memory_range
            self.start.setText(f"{r.start:#05x}")
            self.end.setText(f"{min(r.stop - 1, r.start + 0xFF):#05x}")

    @staticmethod
    def fmt(cells: dict[int, int]) -> str:
        if not cells:
            return ""
        addrs = sorted(cells)
        out = []
        for base in range(addrs[0] & ~0xF, addrs[-1] + 1, 16):
            row = [cells.get(a) for a in range(base, base + 16)]
            hx = " ".join("--" if v is None else f"{v:02X}" for v in row)
            asc = "".join("." if v is None or not 32 <= v < 127 else chr(v) for v in row)
            out.append(f"{base:04X}: {hx}  {asc}")
        return "\n".join(out)

    def dump(self) -> None:
        s = self.session
        if not s:
            return
        try:
            a, b = int(self.start.text(), 0), int(self.end.text(), 0)
        except ValueError:
            return
        self.run(s.dump, a, b, done=lambda c: self.hex.setPlainText(self.fmt(c)), label="Reading EEPROM")

    def backup(self, full: bool) -> None:
        s = self.session
        if s:
            self.run(s.backup, "manual-full" if full else "manual", None, full,
                     done=lambda p: self.win.log(f"Backup saved: {p}"), label="Backing up")

    def restore(self) -> None:
        s = self.session
        if not s:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Restore backup", str(backup_mod.default_dir()), "Backups (*.json)")
        if not path:
            return
        doc = backup_mod.load(path)
        dlg = ConfirmDialog("Restore EEPROM backup",
                            f"Write {len(doc['cells'])} cells from a backup of <b>{doc.get('model')}</b> "
                            f"(serial {doc.get('serial')}, {doc.get('created')}) to this printer?",
                            s.model.name, ["This backup belongs to this printer (or I know what I am doing)."], self)
        if not dlg.exec():
            return
        self.run(s.restore, path, done=lambda r: self.win.log(f"Restore: {'OK' if r.ok else 'FAILED'} (pre-restore backup {r.backup_path})"), label="Restoring")

    def read_one(self) -> None:
        s = self.session
        if not s:
            return
        try:
            a = int(self.addr.text(), 0)
        except ValueError:
            return
        self.run(s.read, a, done=lambda v: (self.val.setText(f"{v:#04x}"), self.win.log(f"{a:#06x} = {v:#04x}")), label="Reading")

    def write_one(self) -> None:
        s = self.session
        if not s:
            return
        try:
            a, v = int(self.addr.text(), 0), int(self.val.text(), 0)
        except ValueError:
            return
        if QMessageBox.warning(self, "Write EEPROM", f"Write {v:#04x} to {a:#06x}? A backup of the cell is taken first.",
                               QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.run(s.write_cells, {a: v}, reason="manual-write", done=lambda r: self.win.log(f"write {a:#06x}: {'OK' if r.ok else 'FAILED'}"), label="Writing")

    def snapshot(self, which: str) -> None:
        s = self.session
        if not s:
            return

        def done(cells):
            self.snaps[which] = cells
            self.win.log(f"Snapshot {which}: {len(cells)} cells")
            if which == "B" and "A" in self.snaps:
                a = self.snaps["A"]
                changed = [(k, a.get(k), v) for k, v in cells.items() if a.get(k) != v]
                self.hex.setPlainText("Changed cells (address: A -> B)\n" + "\n".join(
                    f"{k:#06x}: {o:#04x} -> {n:#04x}" for k, o, n in changed) if changed else "No differences.")
        self.run(s.dump, done=done, label=f"Snapshot {which}")


# --------------------------------------------------------------------------- #
#  Adjustments
# --------------------------------------------------------------------------- #
class AdjustPage(Page):
    title = "Adjustments"

    def __init__(self, win):
        super().__init__(win)
        lay = QHBoxLayout(self)
        self.list = QListWidget()
        self.data = json.loads((files("egm") / "data" / "adjustments.json").read_text(encoding="utf-8"))["adjustments"]
        for a in self.data:
            self.list.addItem(a["name"])
        self.list.currentRowChanged.connect(self.show)
        lay.addWidget(self.list, 1)
        right = QVBoxLayout()
        self.text = QTextBrowser()
        right.addWidget(self.text, 1)
        h = QHBoxLayout()
        self.print_btn = QPushButton("Print check pattern")
        self.print_btn.clicked.connect(self.print_pattern)
        self.value = QSpinBox()
        self.value.setRange(-99, 99)
        self.write_btn = QPushButton("Write value…")
        self.write_btn.clicked.connect(self.write_value)
        h.addWidget(self.print_btn)
        h.addStretch(1)
        h.addWidget(QLabel("Value:"))
        h.addWidget(self.value)
        h.addWidget(self.write_btn)
        right.addLayout(h)
        lay.addLayout(right, 2)
        self.list.setCurrentRow(0)

    def on_session_changed(self) -> None:
        self.show(self.list.currentRow())

    def _cells(self, adj) -> Optional[dict]:
        s = self.session
        return adj.get("cells", {}).get(s.family.name) if s else None

    def show(self, i: int) -> None:
        if i < 0:
            return
        a = self.data[i]
        cells = self._cells(a)
        status = ("<p style='color:#2e7d32'><b>Supported for this model</b> — value cells: "
                  + ", ".join(f"{int(k, 0):#06x}" for k in cells) + "</p>") if cells else (
            "<p style='color:#ef6c00'><b>Value write not available for this model yet.</b> The EEPROM address of this "
            "adjustment is not in the database. You can still print the check pattern, and use EEPROM → Diff to find "
            "the address (adjust once with another tool between snapshots A and B).</p>")
        paper = f"<p>Paper: {a['paper']}</p>" if a.get("paper") else ""
        self.text.setHtml(f"<h3>{a['name']}</h3>{paper}<p>{a['guidance']}</p>{status}")
        if a.get("range"):
            self.value.setRange(*a["range"])
        self.write_btn.setEnabled(bool(cells))
        self.print_btn.setEnabled(a["kind"] == "pattern")

    def print_pattern(self) -> None:
        mp = self.win.pages["Maintenance"]
        mp.print_job("nozzle")

    def write_value(self) -> None:
        s = self.session
        a = self.data[self.list.currentRow()]
        cells = self._cells(a)
        if not s or not cells:
            return
        v = self.value.value() & 0xFF
        payload = {int(k, 0): v for k in cells}
        self.run(s.write_cells, payload, reason=a["id"], done=lambda r: self.win.log(f"{a['name']}: {'OK' if r.ok else 'FAILED'}"), label="Writing")


# --------------------------------------------------------------------------- #
#  Models browser
# --------------------------------------------------------------------------- #
class TroubleshootPage(Page):
    title = "Troubleshooting"

    def __init__(self, win):
        super().__init__(win)
        from .. import troubleshooting as ts
        self.kb = ts.load()
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.series = QComboBox()
        self.series.addItem("Connected / selected printer", "")
        for key, name in self.kb.series_choices():
            self.series.addItem(name, key)
        self.series.currentIndexChanged.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Describe the problem: yellow missing, two lights flashing, E-11, paper jam…")
        self.search.textChanged.connect(self.refresh)
        top.addWidget(QLabel("Printer:"))
        top.addWidget(self.series, 1)
        top.addWidget(self.search, 2)
        lay.addLayout(top)
        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(self.show_item)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        split.addWidget(self.list)
        split.addWidget(self.view)
        split.setSizes([330, 670])
        lay.addWidget(split, 1)
        self.actions = QHBoxLayout()
        lay.addLayout(self.actions)
        self.refresh()

    # -- data -----------------------------------------------------------------
    def _model_name(self) -> Optional[str]:
        if self.session:
            return self.session.model.name
        return self.win.pages["Printer"].model.currentText().strip() or None

    def profile(self):
        key = self.series.currentData()
        if key:
            return self.kb.profile_for_series(key), None
        model = self._model_name()
        return self.kb.profile(model), model

    def on_session_changed(self) -> None:
        self.series.setCurrentIndex(0)
        self.refresh()

    def refresh(self) -> None:
        p, model = self.profile()
        q = self.search.text().strip()
        self.list.blockSignals(True)
        self.list.clear()
        head = QListWidgetItem(f"★ Your printer: {p.name if p.exact else (model or 'generic')}")
        head.setData(Qt.UserRole, ("profile", None))
        self.list.addItem(head)
        hits = self.kb.light_matches(p, q) if q else []
        if hits:
            it = QListWidgetItem(f"   ↳ {len(hits)} matching light/code entr{'y' if len(hits) == 1 else 'ies'}")
            it.setData(Qt.UserRole, ("profile", None))
            self.list.addItem(it)
        guides = self.kb.search(q) if q else self.kb.guides
        cats = [] if q else self.kb.categories()
        if q:
            for g in guides:
                it = QListWidgetItem(g["title"])
                it.setData(Qt.UserRole, ("guide", g["id"]))
                self.list.addItem(it)
        else:
            for c in cats:
                sep = QListWidgetItem(c.upper())
                sep.setFlags(Qt.NoItemFlags)
                self.list.addItem(sep)
                for g in guides:
                    if g["category"] == c:
                        it = QListWidgetItem("   " + g["title"])
                        it.setData(Qt.UserRole, ("guide", g["id"]))
                        self.list.addItem(it)
        self.list.blockSignals(False)
        self.list.setCurrentRow(2 if q and not hits and self.list.count() > 1 else 0)
        self.show_item(self.list.currentItem())

    def show_item(self, item, _prev=None) -> None:
        from .. import troubleshooting as ts
        while self.actions.count():
            w = self.actions.takeAt(0).widget()
            if w:
                w.hide()  # gone at once, not only when the deferred delete runs
                w.deleteLater()
        if item is None or not item.data(Qt.UserRole):
            return
        kind, gid = item.data(Qt.UserRole)
        p, model = self.profile()
        if kind == "profile":
            self.view.setHtml(ts.profile_html(p, model))
            return
        g = self.kb.guide(gid)
        self.view.setHtml(ts.guide_html(g, p))
        self.actions.addStretch(1)
        for a in g.get("actions", []):
            b = self._action_button(a)
            if b:
                self.actions.addWidget(b)

    def _action_button(self, action: str):
        labels = {"nozzle": "Print a nozzle check", "clean_normal": "Run a Normal cleaning…",
                  "waste": "Open Waste ink pads", "release": "Release stuck job",
                  "ink_charge": "Go to ink charge (Maintenance)"}
        if action not in labels:
            return None
        b = QPushButton(labels[action])
        mp = self.win.pages["Maintenance"]

        def go():
            if action == "waste":
                self.win.nav.setCurrentRow(list(self.win.pages).index("Waste ink pads"))
            elif action == "nozzle":
                mp.print_job("nozzle")
            elif action == "release":
                mp.print_job("release")
            elif action == "clean_normal":
                idx = next((i for i in range(mp.clean_combo.count()) if "Normal" in mp.clean_combo.itemText(i)), -1)
                if idx >= 0:
                    mp.clean_combo.setCurrentIndex(idx)
                    mp.run_clean()
            elif action == "ink_charge":
                self.win.nav.setCurrentRow(list(self.win.pages).index("Maintenance"))
                idx = next((i for i in range(mp.clean_combo.count()) if "Charg" in mp.clean_combo.itemText(i)), -1)
                if idx >= 0:
                    mp.clean_combo.setCurrentIndex(idx)
        b.clicked.connect(go)
        b.setEnabled(action == "waste" or self.session is not None)
        return b


class ModelsPage(Page):
    title = "Model database"

    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter models, e.g. L31, ET-28, XP-2")
        self.filter.textChanged.connect(self.fill)
        lay.addWidget(self.filter)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Model", "Reports as", "Family", "Coverage", "Verified", "Featured"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table)
        self.fill("")

    def fill(self, text: str) -> None:
        db = load_db()
        names = db.names() if not text else sorted(m.name for m in db.search(text))
        if not text:
            names = [m.name for m in db.featured()] + [n for n in names if not db.models[n].featured]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for n in names[:2000]:
            m = db.models[n]
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, v in enumerate([m.name, m.model_string, m.family.name, m.coverage, m.verified or "", "★" if m.featured else ""]):
                self.table.setItem(r, c, QTableWidgetItem(v))
        # keep our order (featured first) until the user clicks a header
        self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.table.setSortingEnabled(True)


# --------------------------------------------------------------------------- #
#  Main window
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1060, 760)
        self.session: Optional[PrinterSession] = None
        self.runner = Runner(self)
        self.runner.busy_changed.connect(self._busy)
        # link notices arrive on the worker thread; flush them from the GUI thread
        self._notices: list[str] = []
        self._notice_timer = QTimer(self)
        self._notice_timer.timeout.connect(self._flush_notices)
        self._notice_timer.start(300)
        # printer activity: snapshots arrive from the worker thread via a list
        self.activity = ActivityTracker()
        self._snaps: list = []
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._background_poll)
        self._poll_timer.start(3000)
        self._strip_timer = QTimer(self)
        self._strip_timer.timeout.connect(self._render_strip)
        self._strip_timer.start(500)

        central = QWidget()
        root = QVBoxLayout(central)
        bar = QHBoxLayout()
        self.conn_label = QLabel("Not connected")
        self.conn_label.setStyleSheet("font-weight: 600;")
        self.cov_badge = Badge("", "readonly")
        self.ver_badge = Badge("", "verified")
        self.dry_badge = Badge("DRY RUN", "dry")
        for b in (self.cov_badge, self.ver_badge, self.dry_badge):
            b.hide()
        bar.addWidget(self.conn_label)
        bar.addWidget(self.cov_badge)
        bar.addWidget(self.ver_badge)
        bar.addWidget(self.dry_badge)
        bar.addStretch(1)
        self.busy_label = QLabel()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.hide()
        bar.addWidget(self.busy_label)
        bar.addWidget(self.progress)
        root.addLayout(bar)
        self.strip = StatusStrip()
        root.addWidget(self.strip)

        body = QHBoxLayout()
        self.nav = QListWidget()
        self.nav.setMaximumWidth(190)
        self.stack = QStackedWidget()
        self.pages: dict[str, Page] = {}
        for cls in (ConnectPage, StatusPage, WastePage, MaintenancePage, AdjustPage, CountersPage, EepromPage,
                    TroubleshootPage, ModelsPage):
            p = cls(self)
            self.pages[p.title] = p
            self.nav.addItem(p.title)
            self.stack.addWidget(p)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMaximumHeight(130)
        self.logbox.setFont(mono())
        root.addWidget(self.logbox)
        self.setCentralWidget(central)

        m = self.menuBar().addMenu("&Help")
        a = QAction("Open backup folder", self)
        a.triggered.connect(self.open_backups)
        m.addAction(a)
        a = QAction("About", self)
        a.triggered.connect(self.about)
        m.addAction(a)
        self.log(f"{APP_NAME} {__version__} — {len(load_db().models)} models in database. Backups: {backup_mod.default_dir()}")

    # -- infrastructure -----------------------------------------------------
    def _flush_notices(self) -> None:
        while self._notices:
            self.log(self._notices.pop(0))

    # -- printer activity ------------------------------------------------------
    def _background_poll(self) -> None:
        """Cheap status read every few seconds, only when nothing else is using
        the printer link (jobs report their own readings through on_status)."""
        s = self.session
        if s is None or not self.runner.idle:
            return
        self.runner.submit(s.poll, quiet=True)

    def start_operation(self, name: str, kind: str) -> None:
        """Called by pages when they start something the printer will be busy with."""
        self.activity.start(name, kind)
        self._render_strip()

    def finish_operation(self, result: str = "") -> None:
        self.activity.finish(result)
        self._render_strip()

    def printer_working(self) -> bool:
        last = self.activity.last
        op = self.activity.op
        return bool((last and last.working) or (op and op.finished is None))

    def _render_strip(self) -> None:
        import time
        while self._snaps:
            self.activity.observe(self._snaps.pop(0))
        now = time.monotonic()
        a, op, last = self.activity, self.activity.op, self.activity.last
        if self.session is None:
            self.strip.show_state("offline", "Not connected")
            return
        if op and op.finished is None:
            # an operation we started: give up when the printer never reacted,
            # or after 3x its usual time
            from ..activity import NO_START_SECONDS
            if not op.saw_work and op.elapsed(now) > NO_START_SECONDS:
                a.finish("printer did not react")
                self.log(f"{op.name}: the printer showed no activity for {NO_START_SECONDS}s and probably ignored "
                         "the command. See Troubleshooting for the Epson-driver alternative.")
            elif op.elapsed(now) > 3 * op.typical:
                a.finish("timed out")
            else:
                state = last.label if last else "Starting"
                if last and last.kind == "idle" and not op.saw_work:
                    state = "Waiting for the printer to start"
                self.strip.show_state(
                    last.kind if last and last.kind != "idle" else "busy", f"{op.name} — {state}",
                    last.detail if last else "",
                    f"{fmt_duration(op.elapsed(now))} elapsed · usually ~{fmt_duration(op.typical)}",
                    progress=op.estimate(now), estimate=True)
                return
        if op and op.finished is not None and now - op.finished < 15:
            ok = op.result in ("done", "") or op.result.startswith(op.name)
            self.strip.show_state("done" if op.result == "done" else ("idle" if ok else "busy"),
                                  f"{op.name} — " + ("finished" if op.result == "done" else op.result or "finished"),
                                  "", f"took {fmt_duration(op.elapsed(now))}", progress=1.0)
            return
        if last is None:
            self.strip.show_state("unknown", "Checking printer…", busy=True)
            return
        stale = now - last.at > 20
        detail = last.detail + ("  (last reading %s ago)" % fmt_duration(now - last.at) if stale else "")
        if last.working:
            self.strip.show_state(last.kind, last.label, detail,
                                  f"for {fmt_duration(a.working_for(now))}", busy=True)
        else:
            self.strip.show_state(last.kind, last.label, detail)

    def log(self, msg: str) -> None:
        self.logbox.appendPlainText(_dt.datetime.now().strftime("%H:%M:%S  ") + str(msg))

    def _busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        if not busy:
            self.busy_label.setText("")
            self.progress.setRange(0, 0)

    def run(self, fn, *args, done=None, label: str = "", **kw) -> None:
        self.busy_label.setText(label + "…" if label else "")
        self.progress.setRange(0, 0)

        def prog(i, n):
            self.progress.setRange(0, n)
            self.progress.setValue(i)

        def err(msg, tb):
            self.log(f"ERROR ({label}): {msg}")
            QMessageBox.critical(self, label or "Error", msg)

        self.runner.submit(fn, *args, on_done=done, on_error=err, on_progress=prog, **kw)

    def set_session(self, s: PrinterSession) -> None:
        if self.session and self.session is not s:
            try:
                self.session.close()
            except Exception:
                pass
        self.session = s
        if hasattr(s.link, "on_event"):
            s.link.on_event = lambda msg: self._notices.append(msg)
        self.activity = ActivityTracker()
        s.on_status = self._snaps.append  # list.append is thread-safe; drained on the GUI thread
        self.conn_label.setText(f"{s.model.name}  ·  {s.link.describe()}")
        self.cov_badge.setText(f"coverage: {s.family.coverage}")
        self.cov_badge.set_kind(s.family.coverage)
        self.cov_badge.show()
        if s.model.verified:
            self.ver_badge.setText(f"verified ({s.model.verified})")
            self.ver_badge.show()
        else:
            self.ver_badge.hide()
        self.dry_badge.setVisible(s.dry_run)
        self.log(f"Connected: {s.model.name} (family {s.family.name}) via {s.link.describe()}"
                 + ("" if s.detected else " — model chosen manually"))
        for p in self.pages.values():
            p.on_session_changed()
        self.nav.setCurrentRow(1)

    def disconnect(self) -> None:
        if self.session:
            self.session.close()
            self.session = None
        self.conn_label.setText("Not connected")
        self.activity = ActivityTracker()
        self._render_strip()
        for b in (self.cov_badge, self.ver_badge, self.dry_badge):
            b.hide()
        for p in self.pages.values():
            p.on_session_changed()
        self.log("Disconnected")

    def open_backups(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        d = backup_mod.default_dir()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def about(self) -> None:
        QMessageBox.about(self, APP_NAME, f"<h3>{APP_NAME} {__version__}</h3><p>Open-source Epson maintenance, waste ink "
                          "counter reset and adjustment tool for Windows, macOS and Linux.</p><p>Built on the work of "
                          "epson_print_conf, reinkpy, ez-reset, padzero and epson-usb. Licensed AGPL-3.0-or-later.</p>"
                          f"<p>{DISCLAIMER}</p>")

    def closeEvent(self, e) -> None:  # noqa: N802
        for t in (self._poll_timer, self._strip_timer, self._notice_timer):
            t.stop()
        self.runner.shutdown()
        if self.session:
            self.session.close()
        super().closeEvent(e)


def run(argv=None) -> int:
    app = QApplication.instance() or QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run())
