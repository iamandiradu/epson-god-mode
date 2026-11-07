"""Simulator link: an in-memory printer for a given model.

Built on ``epson_usb.backends.mock`` (a faithful D4 + EPSON-CTRL state machine)
and populated from our model database, so the whole application -- GUI, CLI,
backups, resets -- can be exercised without hardware.  Use ``sim:<MODEL>`` as
the device address, e.g. ``sim:L3111``.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from ..modeldb import Model, load
from .base import Endpoint, TransportError


def _seed_eeprom(model: Model, waste_percent: float = 87.5) -> dict[int, int]:
    fam = model.family
    cells: dict[int, int] = {}
    rng = fam.memory_range
    # deterministic "noise" so dumps look alive
    h = hashlib.sha256(model.name.encode()).digest()
    for i, a in enumerate(rng):
        cells[a] = h[i % len(h)] ^ ((a * 7) & 0xFF)
    for a, v in fam.waste_reset.items():
        cells[a] = v
    # waste counters at `waste_percent`
    for c in fam.waste_counters:
        if not c.max:
            continue
        value = int(c.max * waste_percent / 100.0)
        for i, a in enumerate(c.addresses):
            cells[a] = (value >> (8 * i)) & 0xFF
        shift = 8 * len(c.addresses)
        for e in c.extra:
            part = (value >> shift) & (e["mask"] >> e["shift"])
            cells[e["address"]] = (cells.get(e["address"], 0) & ~e["mask"] & 0xFF) | ((part << e["shift"]) & e["mask"])
            shift += 8
    # serial number
    serial = f"X{model.name.replace('-', '')[:4]:<4}SIM{abs(hash(model.name)) % 100000:05d}"[:10].upper()
    for i, a in enumerate(fam.serial[:10]):
        cells[a] = ord(serial[i]) if i < len(serial) else 0x20
    # plausible counters
    for s in fam.stats:
        regs = s["registers"]
        groups = regs if regs and isinstance(regs[0], list) else [regs]
        for g in groups:
            val = 1234 if len(g) > 1 else 7
            for i, a in enumerate(reversed(g)):  # registers listed MSB first
                cells[a] = (val >> (8 * i)) & 0xFF
    for d in fam.dates:
        regs = d["registers"]
        # First TI received time: (year-2000)*16 + month ... stored as word
        word = (2024 - 2000) * 512 + 32 * 3 + 15  # 2024-03-15
        for i, a in enumerate(reversed(regs)):
            cells[a] = (word >> (8 * i)) & 0xFF
    for f in fam.fatal_registers:
        for a in f["registers"]:
            cells[a] = 0
    # head id: printable chars
    for i, a in enumerate(fam.head_id):
        cells[a] = ord("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"[i % 34])
    return cells


class _SimPrinterFactory:
    """Creates a MockTransport whose fake printer also accepts service commands."""

    @staticmethod
    def build(model: Model, waste_percent: float, locked: bool):
        from epson_usb.backends.mock import MockConfig, MockPrinter, MockTransport
        from epson_usb.status import build_st2

        fam = model.family
        device_id = (f"MFG:EPSON;CMD:ESCPL2,BDC,D4,D4PX,ESCPR1;MDL:{model.model_string or model.name};"
                     f"CLS:PRINTER;DES:EPSON {model.model_string or model.name};").encode()
        eeprom = _seed_eeprom(model, waste_percent)
        serial = "".join(chr(eeprom[a]) for a in fam.serial[:10]) if fam.serial else "SIMSERIAL1"
        cfg = MockConfig(
            model_name=f"Simulated {model.name}",
            serial=serial,
            read_key=tuple(fam.read_key[:2]) if fam.read_key else None,
            write_key=fam.wire_write_key,
            device_id=device_id,
            eeprom_locked=locked,
            eeprom=eeprom,
        )

        class SimPrinter(MockPrinter):
            cleanings: list[int] = []
            refuse_service = False  # imitate firmwares answering ||:84:NA;

            cleaning_until = 0.0
            report_cleaning_state = True

            def _status_elements(self):
                import time as _t
                els = list(super()._status_elements())
                if self.report_cleaning_state and _t.monotonic() < self.cleaning_until:
                    els = [e for e in els if e[0] != 0x01] + [(0x01, b"\x07")]
                inks = bytes([3, 0x01, 0x00, 92, 0x03, 0x01, 60, 0x04, 0x02, 45, 0x05, 0x03, 77])
                els.append((0x0F, inks))
                # mirror the waste counters into the error code
                over = False
                for c in fam.waste_counters:
                    if c.max and c.decode(self.config.eeprom) >= c.max:
                        over = True
                if over:
                    els.append((0x01, b"\x00"))
                    els.append((0x02, b"\x10"))
                return els

            def _eeprom_reply(self, data: bytes) -> bytes:
                if len(data) >= 5 and data[2] == 0x84 and self.refuse_service:
                    return self._block(b"||:84:NA;")
                if len(data) >= 5 and data[2] == 0x84 and self.config.accepts_read_key((data[0], data[1])):
                    SimPrinter.cleanings.append(data[5] if len(data) > 5 else -1)
                    import time as _t
                    self.cleaning_until = _t.monotonic() + 3.0
                    # a cleaning adds a little waste ink
                    for c in fam.waste_counters:
                        if not c.max:
                            continue
                        v = min(c.max, c.decode(self.config.eeprom) + max(1, c.max // 50))
                        for i, a in enumerate(c.addresses):
                            self.config.eeprom[a] = (v >> (8 * i)) & 0xFF
                    return self._block(b"||:OK;")
                return super()._eeprom_reply(data)

        printer = SimPrinter(cfg)
        return MockTransport(cfg, printer=printer), printer


class SimLink:
    kind = "sim"

    def __init__(self, model_name: str, waste_percent: float = 87.5, locked: bool = False):
        db = load()
        model = db.get(model_name)
        if model is None:
            raise TransportError(f"unknown model for simulator: {model_name}")
        try:
            from epson_usb.printer import EpsonUsbPrinter
        except Exception as exc:  # pragma: no cover
            raise TransportError(f"epson-usb package not available: {exc}")
        self.model = model
        transport, self.printer = _SimPrinterFactory.build(model, waste_percent, locked)
        self._usb = EpsonUsbPrinter(transport=transport, auto_open=True)
        self.printed: list[bytes] = []

    def request(self, frame: bytes, tries: Optional[int] = None) -> Optional[bytes]:
        return self._usb.request(frame, tries=tries)

    def describe(self) -> str:
        return f"simulator ({self.model.name})"

    def close(self) -> None:
        self._usb.close()

    def print_target(self) -> Optional[str]:
        return "direct"

    def print_raw(self, job: bytes) -> str:
        """Record the job; a remote-mode CH (head cleaning) behaves like a cleaning."""
        self.printed.append(job)
        if b"REMOTE1CH" in job:
            import time
            p = self.printer
            p.cleaning_until = time.monotonic() + 3.0
            for c in self.model.family.waste_counters:
                if c.max:
                    v = min(c.max, c.decode(p.config.eeprom) + max(1, c.max // 50))
                    for i, a in enumerate(c.addresses):
                        p.config.eeprom[a] = (v >> (8 * i)) & 0xFF
        return f"sent {len(job)} bytes to the simulator"

    @property
    def eeprom(self) -> dict[int, int]:
        return self.printer.config.eeprom


def discover() -> list[Endpoint]:
    return [Endpoint(kind="sim", address=f"sim:{m.name}", label=f"Simulator: {m.name}",
                     model_string=m.model_string) for m in load().featured()[:4]]
