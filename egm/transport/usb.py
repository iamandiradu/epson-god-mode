"""USB link: IEEE 1284.4 over the printer's bulk pipe, via the ``epson-usb`` package.

``epson-usb`` (MIT) gives us the platform plumbing:

* Windows: the driver-provided ``USBPRINT`` device interface -- no Zadig / WinUSB.
* macOS / Linux: ``libusb-1.0`` through ctypes (or PyUSB, or ``/dev/usb/lpN``).
* the D4 handshake, credit handling and interface fallback (some models expose
  a vendor interface that never answers D4; the library walks the candidates).

We only use its *session*; EEPROM semantics (keys, address widths, reset sets)
are ours, driven by the model database.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from .base import Endpoint, TransportError

log = logging.getLogger(__name__)

EPSON_VID = 0x04B8


def available() -> bool:
    try:
        import epson_usb  # noqa: F401
        return True
    except Exception:  # pragma: no cover
        return False


def discover() -> list[Endpoint]:
    """List Epson USB printers reachable right now (without opening them)."""
    try:
        from epson_usb.backends import find_devices
    except Exception as exc:  # pragma: no cover
        log.warning("epson-usb not importable: %s", exc)
        return []
    out: list[Endpoint] = []
    seen: set[str] = set()
    for info in find_devices(vendor_id=EPSON_VID):
        key = f"{info.backend}:{info.path}"
        if key in seen:
            continue
        seen.add(key)
        label = info.description or f"Epson USB printer ({info.vid_pid})"
        model_string = ""
        m = re.search(r"MDL:([^;]+);", (info.extra or {}).get("device_id", "") or "")
        if m:
            model_string = m.group(1).strip()
        if not model_string:
            # Windows interface paths often embed the product name
            m = re.search(r"(?i)(L\d{3,5}|ET-\d{4}|XP-\d{3,4}|WF-\d{4})", info.path or "")
            if m:
                model_string = m.group(1).upper() + " Series"
        out.append(Endpoint(kind="usb", address=info.path, label=f"{label} [{info.backend}]",
                            model_string=model_string,
                            details={"backend": info.backend, "vid": info.vendor_id,
                                     "pid": info.product_id, "serial": info.serial}))
    return out


# Errors after which the link is reopened instead of failing the operation.
# WinErr 5 (ACCESS_DENIED) / 32 / 170 typically mean the handle went stale: the
# printer slept, was power-cycled or re-enumerated, or the Windows spooler /
# Epson Status Monitor grabbed the port for a print job.
RECONNECT_DELAYS = (0.5, 1.0, 2.0, 3.0, 5.0, 8.0)


def is_idempotent(frame: bytes) -> bool:
    """May this EPSON-CTRL frame be sent again after a reconnect?

    Status/identification queries and EEPROM reads are harmless; an EEPROM
    write re-writes the same value. Service commands (cleaning, ink charge),
    ``rw`` and anything unknown are *not* repeated automatically."""
    name = frame[:2]
    if name in (b"st", b"di", b"vi", b"ia"):
        return True
    if name == b"||" and len(frame) >= 7:
        return frame[6] in (0x41, 0x42)  # 'A' read, 'B' write
    return False


class UsbLink:
    kind = "usb"

    def __init__(self, path: Optional[str] = None, backend: Optional[str] = None,
                 interface: Optional[int] = None, dry_run: bool = False,
                 factory=None, sleep=None, on_event=None):
        try:
            from epson_usb.errors import D4Error, DeviceNotFoundError, NoReplyError
            from epson_usb.errors import TransportError as _TE
        except Exception as exc:  # pragma: no cover
            raise TransportError(f"epson-usb package not available: {exc}")
        self.path = path
        self.backend = backend
        self.interface = interface
        self.dry_run = dry_run
        self._factory = factory or self._default_factory
        import time
        self._sleep = sleep or time.sleep
        #: callback(str) for user-visible notices ("reconnected", ...)
        self.on_event = on_event
        self._io_errors = (_TE, D4Error, NoReplyError, OSError)
        self._not_found = DeviceNotFoundError
        self._printer = None
        self.reconnects = 0
        try:
            self._open(path)
        except self._io_errors as exc:
            raise TransportError(_explain(str(exc))) from exc

    # -- lifecycle -------------------------------------------------------------
    def _default_factory(self, path):
        from epson_usb.printer import EpsonUsbPrinter
        kwargs = {}
        if self.interface is not None:
            kwargs["interface"] = self.interface
        return EpsonUsbPrinter(device=path, backend=self.backend, dry_run=self.dry_run,
                               auto_open=True, **kwargs)

    def _open(self, path) -> None:
        self._printer = self._factory(path)
        info = getattr(self._printer, "device_info", None)
        if info is not None and getattr(info, "path", None):
            self.path = info.path

    def _notify(self, msg: str) -> None:
        log.warning(msg)
        if self.on_event:
            try:
                self.on_event(msg)
            except Exception:  # pragma: no cover
                pass

    def suspend(self) -> None:
        """Release the device (e.g. so the spooler can print). The next
        request reopens it automatically."""
        self.close()

    def reconnect(self, reason: str = "") -> None:
        """Close and reopen, first on the same path, then by rediscovery
        (the path changes when Windows re-enumerates the printer)."""
        self.close()
        last: Optional[Exception] = None
        for attempt, delay in enumerate(RECONNECT_DELAYS, 1):
            self._sleep(delay)
            for path in (self.path, None):
                try:
                    self._open(path)
                    self.reconnects += 1
                    self._notify(f"USB link re-established (attempt {attempt}{', ' + reason if reason else ''})")
                    return
                except self._io_errors as exc:
                    last = exc
                    if path is None:
                        break
        raise TransportError(_explain(f"could not reconnect to the printer: {last}"))

    # -- ControlLink -------------------------------------------------------------
    @property
    def released(self) -> bool:
        return self._printer is None

    def try_reopen(self) -> bool:
        """One quick attempt to reopen a released link (no backoff, no notices).
        Used while polling: the spooler / Epson port monitor keeps the port
        while a print or cleaning job runs, so 'access denied' is expected."""
        if self._printer is not None:
            return True
        for path in (self.path, None):
            try:
                self._open(path)
                return True
            except self._io_errors:
                continue
        return False

    def request(self, frame: bytes, tries: Optional[int] = None) -> Optional[bytes]:
        if self._printer is None:
            try:
                self._open(self.path)  # released on purpose: reopen without waiting
            except self._io_errors:
                self.reconnect("device was released")
        try:
            return self._printer.request(frame, tries=tries)
        except self._io_errors as exc:
            first = str(exc)
        self._notify(f"USB I/O error: {first} — reconnecting…")
        self.reconnect(first)
        if not is_idempotent(frame):
            raise TransportError(
                "the printer connection dropped while sending a service command; it was reconnected, "
                "but the command was NOT repeated automatically (it may or may not have run). "
                f"Check the printer and retry if needed. ({first})")
        try:
            return self._printer.request(frame, tries=tries)
        except self._io_errors as exc:
            raise TransportError(_explain(str(exc))) from exc

    def describe(self) -> str:
        if self._printer is None:
            return "USB (released)"
        return self._printer.describe()

    @property
    def device_info(self):
        return self._printer.device_info if self._printer else None

    def close(self) -> None:
        """Leave IEEE 1284.4 packet mode, then release the handle.

        Just closing the handle leaves the printer in D4 mode with our
        EPSON-CTRL channel open; a print job sent through the spooler right
        after can then stall.  D4 ``Exit`` (command 0x08 on the transaction
        channel) closes every channel and returns the printer to normal mode."""
        p, self._printer = self._printer, None
        if p is None:
            return
        session = getattr(p, "session", None)
        if session is not None and getattr(session, "connected", False):
            try:
                session.send(0, 0, bytes([0x08]), credit=1)
                session.recv(500)
            except Exception:  # best effort: the handle is closed regardless
                pass
        try:
            p.close()
        except Exception:  # pragma: no cover
            pass

    def print_target(self) -> Optional[str]:
        return "direct"

    def print_raw(self, job: bytes, chunk: int = 4096, timeout_ms: int = 15000) -> str:
        """Send a print job straight down the USB pipe, like ``escputil`` does
        with /dev/usb/lp0 -- no Windows print queue involved.

        The D4 control session is closed first (D4 ``Exit``), so the printer is
        back in normal mode and reads the pipe as print data. Every job starts
        with the EJL "exit packet mode" sequence anyway, in case the Epson
        status monitor put the printer back into D4 in between. The control
        session reopens automatically on the next request."""
        import time
        backend = None
        info = self.device_info
        if info is not None:
            backend = getattr(info, "backend", None)
        self.close()
        time.sleep(0.3)
        from epson_usb.backends import open_transport
        last: Optional[Exception] = None
        for delay in (0.0, 0.5, 1.0, 2.0, 3.0):
            if delay:
                self._sleep(delay)
            transport = None
            sent = 0
            try:
                transport = open_transport(self.path, backend=backend)
                while sent < len(job):
                    n = transport.write(job[sent:sent + chunk], timeout_ms)
                    if not n:
                        raise TransportError("printer accepted no data (write returned 0)")
                    sent += n
                return f"sent {sent} bytes directly over USB"
            except self._io_errors as exc:
                last = exc
                if sent:
                    # part of the job is already in the printer: never resend it
                    raise TransportError(_explain(f"USB write failed after {sent} of {len(job)} bytes: {exc}")) from exc
            finally:
                if transport is not None:
                    try:
                        transport.close()
                    except Exception:  # pragma: no cover
                        pass
        raise TransportError(_explain(f"could not open the printer for printing: {last}"))


def _explain(msg: str) -> str:
    if "ACCESS_DENIED" in msg or "WinErr 5" in msg:
        return (msg + " — Windows denied access to the printer. Usually the print spooler or Epson "
                "Status Monitor is using it (a print job is running), or the printer went to sleep / was "
                "switched off. Wait for jobs to finish, make sure the printer is on, then retry.")
    if "SHARING_VIOLATION" in msg or "BUSY" in msg:
        return msg + " — the printer is busy (another program has it open)."
    return msg
