"""Small reusable widgets."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QCheckBox, QVBoxLayout, QWidget)


class LevelBar(QWidget):
    """A horizontal bar with a label; colour shifts from green to red with the value."""

    def __init__(self, title: str, parent=None, invert: bool = False):
        super().__init__(parent)
        self.title = title
        self.value: float | None = None
        self.detail = ""
        self.invert = invert  # True for waste counters: high = bad
        self.setMinimumHeight(44)

    def set_value(self, percent: float | None, detail: str = "") -> None:
        self.value = percent
        self.detail = detail
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(self.palette().text().color())
        p.drawText(0, 0, w, 18, Qt.AlignLeft | Qt.AlignVCenter, self.title)
        txt = "—" if self.value is None else (f"{self.value:.1f}%" if self.detail == "" else self.detail)
        p.drawText(0, 0, w, 18, Qt.AlignRight | Qt.AlignVCenter, txt)
        bar_y, bar_h = 22, h - 26
        p.setPen(QPen(QColor(120, 120, 120), 1))
        p.setBrush(QColor(0, 0, 0, 20))
        p.drawRoundedRect(0, bar_y, w - 1, bar_h, 4, 4)
        if self.value is not None:
            v = max(0.0, min(100.0, self.value))
            bad = v if self.invert else 100 - v
            if bad < 60:
                color = QColor(76, 175, 80)
            elif bad < 85:
                color = QColor(255, 179, 0)
            else:
                color = QColor(229, 57, 53)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(1, bar_y + 1, max(2, int((w - 3) * v / 100)), bar_h - 2, 3, 3)
        p.end()


class Badge(QLabel):
    COLORS = {"full": "#2e7d32", "partial": "#ef6c00", "readonly": "#616161", "none": "#b71c1c",
              "verified": "#1565c0", "dry": "#6a1b9a", "warn": "#c62828", "ok": "#2e7d32"}

    def __init__(self, text: str = "", kind: str = "readonly", parent=None):
        super().__init__(text, parent)
        self.set_kind(kind)

    def set_kind(self, kind: str) -> None:
        c = self.COLORS.get(kind, "#616161")
        self.setStyleSheet(f"QLabel {{ background: {c}; color: white; border-radius: 8px; padding: 2px 8px; font-weight: 600; }}")


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


class ConfirmDialog(QDialog):
    """Dangerous-action confirmation: a checklist plus typing the model name."""

    def __init__(self, title: str, text: str, model_name: str, checks: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        self.boxes = []
        for c in checks:
            cb = QCheckBox(c)
            cb.toggled.connect(self._update)
            self.boxes.append(cb)
            lay.addWidget(cb)
        form = QFormLayout()
        self.model_name = model_name
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(model_name)
        self.edit.textChanged.connect(self._update)
        form.addRow(f"Type the model name (<b>{model_name}</b>) to confirm:", self.edit)
        lay.addLayout(form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self._update()

    def _update(self) -> None:
        ok = all(b.isChecked() for b in self.boxes) and self.edit.text().strip().lower() == self.model_name.lower()
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)


def row(*widgets: QWidget, stretch_last: bool = False) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        h.addWidget(x)
    if stretch_last:
        h.addStretch(1)
    return w


class StatusStrip(QFrame):
    """'What is the printer doing' bar: dot + state + detail + elapsed + progress."""

    COLORS = {"idle": "#2e7d32", "printing": "#1565c0", "cleaning": "#1565c0", "charging": "#1565c0",
              "busy": "#ef6c00", "unreachable": "#ef6c00", "paused": "#ef6c00", "error": "#c62828",
              "unknown": "#757575", "offline": "#9e9e9e", "done": "#2e7d32"}

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QProgressBar
        self.setFrameShape(QFrame.StyledPanel)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 4, 8, 4)
        self.dot = QLabel("●")
        self.dot.setFixedWidth(16)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600;")
        self.detail = QLabel()
        self.detail.setStyleSheet("color: palette(mid);")
        self.timeinfo = QLabel()
        self.bar = QProgressBar()
        self.bar.setFixedWidth(240)
        self.bar.setTextVisible(True)
        h.addWidget(self.dot)
        h.addWidget(self.title)
        h.addWidget(self.detail, 1)
        h.addWidget(self.timeinfo)
        h.addWidget(self.bar)
        self.show_state("offline", "Not connected")

    def show_state(self, kind: str, title: str, detail: str = "", timeinfo: str = "",
                   progress: float | None = None, busy: bool = False, estimate: bool = False) -> None:
        self.dot.setStyleSheet(f"color: {self.COLORS.get(kind, '#757575')}; font-size: 16px;")
        self.title.setText(title)
        self.detail.setText(detail)
        self.detail.setToolTip(detail)
        self.timeinfo.setText(timeinfo)
        if progress is not None:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(progress * 1000))
            self.bar.setFormat(("~%p%" if estimate else "%p%"))
            self.bar.show()
        elif busy:
            self.bar.setRange(0, 0)  # indeterminate animation
            self.bar.show()
        else:
            self.bar.hide()
