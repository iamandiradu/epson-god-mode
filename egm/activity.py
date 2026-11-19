"""What is the printer doing right now?  Turns status polls into a simple activity.

The printer never reports a percentage for maintenance work, only a state
(printing, cleaning, charging, busy...).  For operations the app starts itself
it does know roughly how long they take, so a progress *estimate* is derived
from the elapsed time and a typical duration, capped below 100 % until the
printer reports it is idle again.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .protocol import PrinterStatus

# Typical durations (seconds) on L/ET-series ink tank printers. Rough by design:
# they only drive an estimate, the real end comes from the printer's state.
TYPICAL_SECONDS = {
    "nozzle_check": 45,
    "head_cleaning": 75,
    "power_cleaning": 180,
    "ink_charge": 420,
    "ink_discharge": 240,
    "print": 60,
}

KIND_FOR_STATE = {
    0x00: "error", 0x01: "printing", 0x02: "busy", 0x03: "printing", 0x04: "idle", 0x05: "paused",
    0x06: "busy", 0x07: "cleaning", 0x08: "busy", 0x09: "busy", 0x0A: "busy", 0x0B: "busy",
    0x0C: "busy", 0x0F: "printing", 0x11: "charging",
}
LABEL_FOR_KIND = {
    "idle": "Ready", "printing": "Printing", "cleaning": "Cleaning", "charging": "Charging ink",
    "busy": "Busy", "paused": "Paused", "error": "Error", "unreachable": "Working (port in use)",
    "unknown": "Unknown",
}


@dataclass
class Snapshot:
    """One observation of the printer."""
    kind: str                     # idle/printing/cleaning/charging/busy/paused/error/unreachable/unknown
    label: str
    detail: str = ""
    at: float = field(default_factory=time.monotonic)

    @property
    def working(self) -> bool:
        return self.kind in ("printing", "cleaning", "charging", "busy", "unreachable")


def snapshot_from_status(st: Optional[PrinterStatus]) -> Snapshot:
    if st is None:
        # The port is held by someone else (spooler / Epson monitor) -- in
        # practice that means a job is running.
        return Snapshot("unreachable", LABEL_FOR_KIND["unreachable"],
                        "the printer's USB port is busy, usually because it is printing or cleaning")
    if st.state_code is None:
        return Snapshot("unknown", LABEL_FOR_KIND["unknown"], st.parse_error or "")
    kind = KIND_FOR_STATE.get(st.state_code, "busy")
    if st.error:
        kind = "error"
    label = LABEL_FOR_KIND[kind]
    detail = st.error or (st.state if kind != "idle" and st.state.lower() != label.lower() else "")
    if st.warnings and kind == "idle":
        detail = "; ".join(st.warnings)
    return Snapshot(kind, label, detail)


@dataclass
class Operation:
    """Something the app started and is waiting for."""
    name: str
    kind: str                     # key into TYPICAL_SECONDS
    started: float = field(default_factory=time.monotonic)
    saw_work: bool = False        # printer has reported working at least once
    finished: Optional[float] = None
    result: str = ""

    @property
    def typical(self) -> float:
        return float(TYPICAL_SECONDS.get(self.kind, 60))

    def elapsed(self, now: Optional[float] = None) -> float:
        end = self.finished if self.finished is not None else (now or time.monotonic())
        return max(0.0, end - self.started)

    def estimate(self, now: Optional[float] = None) -> float:
        """0..1 progress estimate; never reaches 1 until finished."""
        if self.finished is not None:
            return 1.0
        frac = self.elapsed(now) / self.typical
        # ease towards 95 % if it runs long, instead of sitting at 100 %
        return min(0.95, frac if frac < 0.9 else 0.9 + (1 - 1 / (1 + (frac - 0.9))) * 0.05)


# If the printer shows no sign of work this long after a job was sent, it
# almost certainly ignored the command.
NO_START_SECONDS = 60


class ActivityTracker:
    """Combines status snapshots with the operation the app is running."""

    def __init__(self) -> None:
        self.last: Optional[Snapshot] = None
        self.since: Optional[float] = None    # when the current kind started
        self.op: Optional[Operation] = None

    def start(self, name: str, kind: str) -> Operation:
        self.op = Operation(name, kind)
        return self.op

    def finish(self, result: str = "") -> None:
        if self.op and self.op.finished is None:
            self.op.finished = time.monotonic()
            self.op.result = result

    def observe(self, snap: Snapshot) -> None:
        if self.last is None or snap.kind != self.last.kind:
            self.since = snap.at
        self.last = snap
        op = self.op
        if op and op.finished is None:
            if snap.working:
                op.saw_work = True
            elif snap.kind == "idle" and op.saw_work:
                self.finish("done")

    def working_for(self, now: Optional[float] = None) -> float:
        if self.since is None:
            return 0.0
        return max(0.0, (now or time.monotonic()) - self.since)


def fmt_duration(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}" if s >= 60 else f"{s}s"
