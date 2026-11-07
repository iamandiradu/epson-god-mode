"""High-level printer operations shared by the CLI and the GUI.

A :class:`PrinterSession` owns one open link, knows which model it talks to and
enforces the safety rules:

* every write is preceded by an automatic EEPROM backup;
* writes are verified by reading back;
* a model whose family has no write key cannot write at all;
* ``dry_run`` turns every write into a log line.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import backup as _backup
from .modeldb import Family, Model, ModelDB, load as load_db
from .protocol import EepromRefused, EpsonCtrl, PrinterStatus, ProtocolError
from .transport import ControlLink, TransportError, open_link

log = logging.getLogger(__name__)
Progress = Optional[Callable[[int, int], None]]


class SafetyError(RuntimeError):
    """An operation was refused by our own safety rules (not by the printer)."""


class ServiceRefused(ProtocolError):
    """The printer answered ``:NA;`` to a service (cleaning / charge) command."""

    def __init__(self, msg: str, option: dict):
        super().__init__(msg)
        self.option = option


@dataclass
class WasteLevel:
    index: int
    name: str
    value: int
    max: Optional[int]
    percent: Optional[float]
    addresses: list[int]

    @property
    def text(self) -> str:
        if self.percent is None:
            return f"{self.value} (limit unknown)"
        return f"{self.percent:.1f}%  ({self.value} / {self.max})"


@dataclass
class ResetReport:
    backup_path: Optional[Path]
    before: dict[int, int]
    written: dict[int, int]
    after: dict[int, int]
    dry_run: bool
    ok: bool
    messages: list[str] = field(default_factory=list)


@dataclass
class PrinterInfo:
    model: str
    family: str
    coverage: str
    verified: Optional[str]
    model_string: str
    device_id: str
    firmware: Optional[str]
    serial: Optional[str]
    link: str
    link_kind: str
    detected: bool          # model came from the device id (not user-forced)


class PrinterSession:
    def __init__(self, link: ControlLink, model: Model, db: ModelDB, *, dry_run: bool = False,
                 detected: bool = True, device_id: str = ""):
        self.link = link
        self.model = model
        self.db = db
        self.dry_run = dry_run
        self.detected = detected
        self.device_id = device_id
        self.ctl = EpsonCtrl(link, model.family)
        self.backup_dir: Optional[Path] = None
        self._serial: Optional[str] = None

    # ------------------------------------------------------------------ #
    #  Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def connect(cls, address: Optional[str] = None, model: Optional[str] = None, *,
                dry_run: bool = False, **link_kw) -> "PrinterSession":
        """Open the link, identify the printer, pick the model."""
        db = load_db()
        link = open_link(address, dry_run=dry_run, **link_kw)
        device_id = ""
        detected_model: Optional[Model] = None
        try:
            probe = EpsonCtrl(link, _probe_family())
            device_id = probe.device_id()
        except (TransportError, ProtocolError) as exc:
            log.debug("device id probe failed: %s", exc)
        mdl = _mdl_from_device_id(device_id)
        if mdl:
            detected_model = db.detect(mdl, hint=model)
        chosen: Optional[Model] = None
        detected = False
        if model:
            chosen = db.get(model)
            if chosen is None:
                link.close()
                raise SafetyError(f"unknown model '{model}'. Use --list-models to see the database.")
            if detected_model and detected_model.family is not chosen.family:
                log.warning("Printer reports '%s' (%s family) but '%s' (%s family) was forced",
                            mdl, detected_model.family.name, chosen.name, chosen.family.name)
        elif detected_model:
            chosen, detected = detected_model, True
        else:
            link.close()
            raise SafetyError(
                f"could not identify the printer (device id: {device_id or 'none'}). "
                "Select the model explicitly.")
        return cls(link, chosen, db, dry_run=dry_run, detected=detected, device_id=device_id)

    def close(self) -> None:
        self.link.close()

    def __enter__(self) -> "PrinterSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def family(self) -> Family:
        return self.model.family

    # ------------------------------------------------------------------ #
    #  Identification / status
    # ------------------------------------------------------------------ #
    def info(self) -> PrinterInfo:
        fw = None
        try:
            fw = self.ctl.firmware_version()
        except (TransportError, ProtocolError):
            pass
        return PrinterInfo(
            model=self.model.name, family=self.family.name, coverage=self.family.coverage,
            verified=self.model.verified, model_string=self.model.model_string,
            device_id=self.device_id, firmware=fw, serial=self.serial(), link=self.link.describe(),
            link_kind=self.link.kind, detected=self.detected,
        )

    def status(self) -> PrinterStatus:
        return self.ctl.status()

    def serial(self, refresh: bool = False) -> Optional[str]:
        if self._serial and not refresh:
            return self._serial
        s = None
        try:
            st = self.ctl.status()
            s = st.serial
        except (TransportError, ProtocolError):
            pass
        if not s and self.family.serial and self.family.read_key:
            try:
                cells = self.ctl.read_many(self.family.serial)
                s = "".join(chr(v) if 32 <= v < 127 else "?" for v in cells.values()).strip()
            except (TransportError, ProtocolError):
                s = None
        self._serial = s or None
        return self._serial

    # ------------------------------------------------------------------ #
    #  Waste ink counters
    # ------------------------------------------------------------------ #
    def waste_levels(self) -> list[WasteLevel]:
        fam = self.family
        if not fam.waste_counters:
            return []
        addrs = sorted({a for c in fam.waste_counters for a in c.all_addresses})
        cells = self.ctl.read_many(addrs)
        out = []
        names = ["Main pad (waste ink counter 1)", "Borderless / secondary pad (counter 2)",
                 "Counter 3", "Counter 4", "Counter 5", "Counter 6"]
        for i, c in enumerate(fam.waste_counters):
            out.append(WasteLevel(i, names[i] if i < len(names) else f"Counter {i + 1}",
                                  c.decode(cells), c.max, c.percent(cells), c.all_addresses))
        return out

    def reset_waste(self, *, acknowledge_pads_replaced: bool, progress: Progress = None) -> ResetReport:
        """Write the family's reset sequence after a backup; verify every byte."""
        fam = self.family
        if not acknowledge_pads_replaced:
            raise SafetyError("refusing to reset: you must acknowledge the waste pads were replaced/serviced")
        if not fam.waste_reset:
            raise SafetyError(f"no reset sequence known for family {fam.name} (coverage: {fam.coverage})")
        if not fam.can_write and not self.dry_run:
            raise SafetyError(f"family {fam.name} has no write key; a write would be refused by the printer")
        masks = fam.reset_masks
        if masks is None:
            raise SafetyError("this family's reset needs a completion step in an unsupported form; "
                              "refusing to perform a partial reset")
        targets = dict(fam.waste_reset)
        before = self.ctl.read_many(sorted(set(targets) | set(masks)))
        bpath = self.backup("before-waste-reset", cells=before)
        written: dict[int, int] = {}
        msgs: list[str] = []
        n = len(targets)
        for i, (addr, val) in enumerate(targets.items()):
            if self.dry_run:
                msgs.append(f"DRY RUN: would write {addr:#06x} <- {val:#04x} (was {before.get(addr, 0):#04x})")
            else:
                self.ctl.write(addr, val, verify=True)
            written[addr] = val
            if progress:
                progress(i + 1, n)
        # completion step: AND-mask flag bytes, read fresh after the counter writes
        for addr, mask in masks.items():
            cur = self.ctl.read(addr)
            new = cur & mask
            if new == cur:
                continue
            if self.dry_run:
                msgs.append(f"DRY RUN: would write {addr:#06x} <- {new:#04x} (was {cur:#04x}, mask {mask:#04x})")
            else:
                self.ctl.write(addr, new, verify=True)
            written[addr] = new
        after = self.ctl.read_many(written.keys()) if not self.dry_run else dict(before)
        ok = self.dry_run or all(after.get(a) == v for a, v in written.items())
        if ok and not self.dry_run:
            msgs.append("All reset cells verified. Power-cycle the printer to clear the error.")
        return ResetReport(bpath, before, written, after, self.dry_run, ok, msgs)

    def temporary_reset(self) -> str:
        """Firmware ``rw`` command keyed by the serial (helps on locked firmwares)."""
        s = self.serial()
        if not s:
            raise SafetyError("serial number unknown; the rw command needs it")
        if self.dry_run:
            return f"DRY RUN: would send rw for serial {s}"
        r = self.ctl.rw_reset(s) or b""
        return r.decode("latin-1", "replace").strip("\x00\x0c\r\n")

    # ------------------------------------------------------------------ #
    #  EEPROM
    # ------------------------------------------------------------------ #
    def read(self, addr: int) -> int:
        return self.ctl.read(addr)

    def read_many(self, addrs, progress: Progress = None) -> dict[int, int]:
        return self.ctl.read_many(addrs, progress=progress)

    def dump(self, start: Optional[int] = None, end: Optional[int] = None, progress: Progress = None) -> dict[int, int]:
        rng = self.family.memory_range
        s = rng.start if start is None else start
        e = (rng.stop - 1) if end is None else end
        return self.ctl.read_many(range(s, e + 1), progress=progress)

    def backup(self, reason: str, cells: Optional[dict[int, int]] = None, full: bool = False,
               progress: Progress = None) -> Path:
        if cells is None:
            cells = self.dump(progress=progress) if full else self.ctl.read_many(
                self.family.interesting_addresses(), progress=progress)
        return _backup.save(cells, model=self.model.name, family=self.family.name, serial=self.serial(),
                            reason=reason, link=self.link.describe(), directory=self.backup_dir,
                            extra={"device_id": self.device_id})

    def write_cells(self, cells: dict[int, int], *, reason: str, progress: Progress = None) -> ResetReport:
        """Generic guarded write (used by restore, extra operations, manual edits)."""
        fam = self.family
        if not cells:
            raise SafetyError("nothing to write")
        for a, v in cells.items():
            if a not in fam.memory_range:
                raise SafetyError(f"address {a:#06x} outside this family's EEPROM range")
            if not 0 <= v <= 0xFF:
                raise SafetyError(f"value {v} for {a:#06x} is not a byte")
        if not fam.can_write and not self.dry_run:
            raise SafetyError(f"family {fam.name} has no write key")
        before = self.ctl.read_many(cells.keys())
        bpath = self.backup(f"before-{reason}", cells=before)
        msgs = []
        n = len(cells)
        for i, (a, v) in enumerate(cells.items()):
            if self.dry_run:
                msgs.append(f"DRY RUN: would write {a:#06x} <- {v:#04x} (was {before.get(a, 0):#04x})")
            else:
                self.ctl.write(a, v, verify=True)
            if progress:
                progress(i + 1, n)
        after = self.ctl.read_many(cells.keys()) if not self.dry_run else dict(before)
        ok = self.dry_run or all(after.get(a) == v for a, v in cells.items())
        return ResetReport(bpath, before, dict(cells), after, self.dry_run, ok, msgs)

    def restore(self, backup_path: Path | str, progress: Progress = None) -> ResetReport:
        doc = _backup.load(backup_path)
        if doc.get("family") and doc["family"] != self.family.name:
            raise SafetyError(f"backup is for family {doc['family']}, printer is {self.family.name}")
        return self.write_cells(doc["cells"], reason="restore", progress=progress)

    # ------------------------------------------------------------------ #
    #  Counters, dates, fatal errors
    # ------------------------------------------------------------------ #
    def counters(self) -> dict[str, object]:
        fam = self.family
        wanted: set[int] = set()
        for s in fam.stats:
            regs = s["registers"]
            for g in (regs if regs and isinstance(regs[0], list) else [regs]):
                wanted.update(g)
        for d in fam.dates:
            wanted.update(d["registers"])
        for f in fam.fatal_registers:
            wanted.update(f["registers"])
        if not wanted:
            return {}
        cells = self.ctl.read_many(sorted(wanted))
        out: dict[str, object] = {}
        for s in fam.stats:
            regs = s["registers"]
            groups = regs if regs and isinstance(regs[0], list) else [regs]
            vals = [_be(cells, g) for g in groups]
            v = vals[0] if len(vals) == 1 else vals
            if s.get("format") == "hex":
                v = f"{v:#x}" if isinstance(v, int) else v
            out[s["name"]] = v
        for d in fam.dates:
            raw = _be(cells, d["registers"])
            out[d["name"]] = _decode_ti_date(raw)
        for f in fam.fatal_registers:
            code = _be(cells, f["registers"])
            desc = self.db.fatal_text(fam, f["table"], code)
            if code == 0:
                out[f["name"]] = "none"
            else:
                out[f["name"]] = f"{code:#06x}: " + (desc["text"] if desc else "unknown code")
        return out

    # ------------------------------------------------------------------ #
    #  Service commands
    # ------------------------------------------------------------------ #
    def cleaning_options(self) -> list[dict]:
        return [c for c in self.family.cleaning if c.get("type") == "service" and c.get("data")]

    # States in which the printer is visibly doing maintenance.
    _CLEANING_STATES = {0x07, 0x02, 0x11}  # cleaning, busy, charging

    def cleaning_blockers(self, st: Optional[PrinterStatus] = None) -> list[str]:
        """Reasons, read from the status block, why the printer refuses cleaning."""
        st = st or self.ctl.status()
        out = []
        if st.error:
            out.append(f"printer error: {st.error}")
        if st.state_code is not None and st.state_code not in (0x03, 0x04):
            out.append(f"printer is not idle ({st.state})")
        for w in st.warnings:
            if "Cleaning disabled" in w or "Ink low" in w:
                out.append(w)
        return out

    def _waste_total(self) -> Optional[int]:
        try:
            return sum(w.value for w in self.waste_levels())
        except (TransportError, ProtocolError):
            return None

    def _quiet_status(self) -> Optional[PrinterStatus]:
        """Status without the long reconnect backoff: None if the port is busy."""
        link = self.link
        if getattr(link, "released", False):
            if not link.try_reopen():
                return None
        try:
            return self.ctl.status()
        except (TransportError, ProtocolError):
            close = getattr(link, "suspend", None)
            if close:
                close()
            return None

    def confirm_maintenance(self, waste_before: Optional[int], timeout: float = 120.0,
                            poll: float = 2.0, sleep=None) -> tuple[bool, str]:
        """Decide whether a cleaning really ran.

        Evidence, strongest first: the waste ink counter went up (every cleaning
        flushes ink into the pads); the printer reported a cleaning/busy state;
        the port was held by the spooler / port monitor for a while (weak).
        Polls without long reconnect waits until the printer is idle again."""
        import time
        sleep = sleep or time.sleep
        end = time.monotonic() + timeout
        saw_state: Optional[str] = None
        locked_polls = 0
        while time.monotonic() < end:
            st = self._quiet_status()
            if st is None:
                locked_polls += 1
            elif st.state_code in self._CLEANING_STATES:
                saw_state = st.state
            elif st.state_code in (0x03, 0x04) and (saw_state or locked_polls):
                break  # back to idle after something happened
            elif st.state_code in (0x03, 0x04) and time.monotonic() > end - timeout + 10:
                break  # idle for 10 s and nothing observed: stop waiting early
            sleep(poll)
        after = self._waste_total()
        if waste_before is not None and after is not None and after > waste_before:
            return True, f"waste ink counter rose by {after - waste_before} (cleaning ran)"
        if saw_state:
            return True, f"printer reported '{saw_state}'"
        if waste_before is not None and after is not None:
            return False, "waste ink counter did not change"
        if locked_polls:
            return False, "could not read the printer while the job ran (port busy); result unknown"
        return False, "no sign of a cleaning"

    def wait_for_maintenance(self, timeout: float = 25.0, poll: float = 1.0) -> Optional[str]:
        ok, why = self.confirm_maintenance(None, timeout=timeout, poll=poll)
        return why if ok else None

    def print_job(self, job: bytes, target: str = "direct", job_name: str = "Epson God Mode") -> str:
        """Send a print job.  ``target`` "direct" = straight to the connected
        printer (USB pipe or network port 9100), otherwise a Windows/CUPS queue
        name, ``ip[:port]`` or ``file:<path>``."""
        from . import printjobs as pj
        if self.dry_run and not target.startswith("file:"):
            return f"DRY RUN: would send {len(job)} bytes to {target}"
        if target == "direct":
            raw = getattr(self.link, "print_raw", None)
            if raw is None:
                raise SafetyError("this connection cannot print directly; choose a print queue")
            if b"REMOTE1" in job:
                pj.assert_well_formed(job)
            return raw(job)
        if not target.startswith("file:"):
            suspend = getattr(self.link, "suspend", None)
            if suspend:
                suspend()  # let the spooler open the port; the next request reconnects
        return pj.send(job, target, job_name=job_name)

    def run_cleaning(self, option_index: int, fallback_target: Optional[str] = "direct",
                     confirm_timeout: float = 120.0) -> str:
        """Head cleaning with a confirmed result.

        1. Factory service command on the control channel (``||`` 0x84 <level>).
        2. If refused (``||:84:NA;``): read the status and report *why* (error,
           not idle, "cleaning disabled", ink low) instead of retrying blindly.
        3. Otherwise send the Epson-driver cleaning job (remote mode ``CH``,
           escputil framing) to ``fallback_target``; Strong uses power cleaning.
        After 1 or 3 the status is polled to confirm the printer really started.
        """
        opts = self.cleaning_options()
        if not 0 <= option_index < len(opts):
            raise SafetyError("no such cleaning option")
        opt = opts[option_index]
        data = bytes(opt["data"])
        if self.dry_run:
            return f"DRY RUN: would send service command {data.hex()} ({opt['name']})"
        before = self.ctl.status()
        blockers = self.cleaning_blockers(before)
        if blockers:
            raise ServiceRefused(f"{opt['name']} not sent — the printer reports: " + "; ".join(blockers), opt)
        waste_before = self._waste_total()
        r = self.ctl.service(data) or b""
        txt = r.decode("latin-1", "replace").strip("\x00\x0c\r\n").replace("@BDC PS", "").strip()
        if b":NA;" not in r:
            ok, why = self.confirm_maintenance(waste_before, timeout=confirm_timeout)
            if ok:
                return f"{opt['name']}: done — {why} (control channel)"
            return f"{opt['name']}: the printer accepted the command but it could not be confirmed ({why})"
        if not fallback_target:
            raise ServiceRefused(f"{opt['name']} refused on the control channel ({txt}) and no print queue "
                                 "is selected for the driver-style cleaning", opt)
        if opt.get("kind") == "charging":
            raise ServiceRefused(f"{opt['name']} refused on the control channel ({txt}); there is no driver-style "
                                 "equivalent for an ink charge", opt)
        from . import printjobs as pj
        power = data and data[0] >= 4  # Strong -> power cleaning
        job = pj.head_cleaning(power=bool(power))
        if fallback_target.startswith("file:"):
            return f"{opt['name']}: control channel refused ({txt}); " + pj.send(job, fallback_target)
        res = self.print_job(job, fallback_target, job_name=f"EGM {opt['name']}")
        ok, why = self.confirm_maintenance(waste_before, timeout=confirm_timeout)
        kind = "power cleaning" if power else "head cleaning"
        via = "directly to the printer" if fallback_target == "direct" else f"via '{fallback_target}'"
        how = f"control channel refused, sent Epson-driver {kind} {via}"
        if ok:
            return f"{opt['name']}: done — {why} ({how})"
        return (f"{opt['name']}: not confirmed — {why} ({how}; {res}). If the printer did not move, "
                "check that the selected queue is this printer and that no job is stuck in it.")

    def extra_operations(self) -> list[dict]:
        return list(self.family.extra_operations)

    def run_extra_operation(self, index: int, progress: Progress = None) -> ResetReport:
        ops = self.extra_operations()
        if not 0 <= index < len(ops):
            raise SafetyError("no such operation")
        op = ops[index]
        cells = {int(k): int(v) for k, v in op["write"].items()}
        return self.write_cells(cells, reason=re.sub(r"[^a-z0-9]+", "-", op["name"].lower()), progress=progress)

    def set_first_ti_date(self, date: _dt.date) -> ResetReport:
        regs = next((d["registers"] for d in self.family.dates if "First TI" in d["name"]), None)
        if not regs or len(regs) != 2:
            raise SafetyError("this family has no First-TI date registers")
        n = (date.year - 2000) * 16 * 32 + 32 * date.month + date.day
        return self.write_cells({regs[0]: n // 256, regs[1]: n % 256}, reason="first-ti-date")


# ---------------------------------------------------------------------- #
#  helpers
# ---------------------------------------------------------------------- #
def _be(cells: dict[int, int], regs: list[int]) -> int:
    total = 0
    for a in regs:  # registers are listed most-significant first
        total = (total << 8) | (cells.get(a, 0) & 0xFF)
    return total


def _decode_ti_date(raw: int) -> str:
    try:
        year = 2000 + raw // (16 * 32)
        month = (raw - (year - 2000) * 512) // 32
        day = raw - (year - 2000) * 512 - 32 * month
        return _dt.date(year, month, day).isoformat()
    except Exception:
        return f"raw {raw:#06x}"


def _mdl_from_device_id(did: str) -> str:
    m = re.search(r"MDL:([^;]+);", did or "")
    return m.group(1).strip() if m else ""


def _probe_family() -> Family:
    """A keyless pseudo-family: enough for ``di``/``st``/``vi``."""
    return Family(name="probe", read_key=[], write_key=None, readlen=2, sendlen=2, coverage="none",
                  models=[], waste_counters=[], waste_reset={}, waste_reset_close=[], stats=[], dates=[],
                  fatal_registers=[], fatal_tables=[], cleaning=[], serial=[], head_id=[],
                  memory={"low": 0, "high": 0xFF}, extra_operations=[], usb_id=[], net_id=[])
