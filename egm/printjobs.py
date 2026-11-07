"""Raw print jobs: nozzle check, head cleaning, test patterns, service commands.

These go down the *data* path (the printer's print queue or port 9100), not
the EPSON-CTRL channel.  Two job styles exist:

* **Remote Mode** (``ESC (R ... REMOTE1``) commands such as ``NC`` (nozzle
  check) and ``CH`` (head cleaning) -- what the Epson driver utility sends.
* **ESC | factory commands** -- the same ``<rkey> <opcode triplet> <data>``
  payload as an EPSON-CTRL ``||`` frame, wrapped as ``1B 7C <len16> ...`` in a
  print job.  This is how Epson's own adjustment program drives ink discharge
  and cleaning (see ``F2_discharge.prn``).

Delivery: Windows -> spooler RAW datatype (pywin32); macOS/Linux -> ``lp -o raw``
or a ``/dev/usb/lpN`` device; network -> TCP 9100.  Every job can also be saved
to a ``.prn`` file.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import struct
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .modeldb import Family
from .protocol import opcode

EXIT_PACKET_MODE = b"\x00\x00\x00\x1b\x01@EJL 1284.4\n@EJL     \n"
INIT = b"\x1b@"


def _remote(cmd: str, args: bytes = b"") -> bytes:
    return cmd.encode() + struct.pack("<H", len(args)) + args


ENTER_REMOTE = INIT + INIT + b"\x1b" + _remote("(R", b"\x00REMOTE1")
EXIT_REMOTE = b"\x1b\x00\x00\x00"
JOB_END = _remote("JE", b"\x00")


def _timer() -> bytes:
    import datetime
    now = datetime.datetime.now()
    return _remote("TI", b"\x00" + now.year.to_bytes(2, "big") + bytes([now.month, now.day, now.hour, now.minute, now.second]))


# --------------------------------------------------------------------------- #
#  Job builders
# --------------------------------------------------------------------------- #
# gutenprint escputil: every remote command is wrapped as
#   ESC @ ESC (R 08 00 00 "REMOTE1" <cmd> <len16> <args> ESC 00 00 00 ESC 00
# and every job ends with  FF ESC 00 ESC 00.  The form feed is what closes the
# page: without it the printer keeps the nozzle-check page open and waits for
# more data (field report, L3111: stalls mid-pattern with a high-pitched whine
# until another job arrives).
ESCPUTIL_REMOTE_HDR = b"\x1b@\x1b(R\x08\x00\x00REMOTE1"
ESCPUTIL_REMOTE_TRAILER = b"\x1b\x00\x00\x00\x1b\x00"
JOB_TRAILER = b"\x0c\x1b\x00\x1b\x00"


def _escputil_remote(cmd: str, args: bytes) -> bytes:
    return ESCPUTIL_REMOTE_HDR + _remote(cmd, args) + ESCPUTIL_REMOTE_TRAILER


def nozzle_check(variant: int = 0) -> bytes:
    """Nozzle check exactly as ``escputil -n`` sends it (VI, NC, form feed)."""
    nc_args = b"\x00\x00" if variant == 0 else b"\x00\x10"
    return b"".join([EXIT_PACKET_MODE, b"\x1b@",
                     _escputil_remote("VI", b"\x00\x00"),
                     _escputil_remote("NC", nc_args),
                     JOB_TRAILER])


def release_stuck_job() -> bytes:
    """Finish a page the printer is still holding open: form feed + resets.
    Ejects the (partly printed) sheet; if nothing is pending the printer
    ignores it."""
    return b"".join([EXIT_PACKET_MODE, b"\x1b@", JOB_TRAILER])


def assert_well_formed(job: bytes) -> None:
    """Nothing but resets / a form feed may follow the last exit from remote
    mode (anything else is printed as text and leaves a page open)."""
    last = max(job.rfind(EXIT_REMOTE), job.rfind(ESCPUTIL_REMOTE_TRAILER))
    if last < 0:
        return
    tail = job[last + len(EXIT_REMOTE):]
    if tail.replace(b"\x1b\x00", b"").replace(b"\x1b@", b"").strip(b"\x00\r\n\x0c"):
        raise ValueError(f"job has data after leaving remote mode: {tail[:16]!r}")


def head_cleaning(group: int = 0, power: bool = False) -> bytes:
    """Head cleaning as ``escputil -c`` sends it (remote ``CH``, then the
    form-feed trailer).  ``group`` 0 = all colours; ``power`` sets bit 0x10
    (power cleaning on models that support it)."""
    g = (group & 0x0F) | (0x10 if power else 0)
    return b"".join([EXIT_PACKET_MODE, b"\x1b@", _escputil_remote("CH", b"\x00" + bytes([g])), JOB_TRAILER])


def esc_pipe(fam: Family, op: int, data: bytes = b"") -> bytes:
    """One ``ESC | 00 <len16> <rkey> <opcode triplet> <data>`` factory command."""
    payload = bytes(fam.read_key[:2]) + opcode(op) + data
    return b"\x1b|\x00" + struct.pack("<H", len(payload)) + payload


def service_job(fam: Family, op: int, data: bytes = b"") -> bytes:
    return INIT + esc_pipe(fam, op, data) + INIT


def service_cleaning_job(fam: Family, level: int) -> bytes:
    """Service-level cleaning (1 gentle .. 4 strong) as a print job."""
    return service_job(fam, 0x84, bytes([level]))


def ink_charge_job(fam: Family) -> bytes:
    return service_job(fam, 0x84, b"\xff")


def service_jobs() -> dict:
    """Recorded factory job scripts (``egm/data/service_jobs.json``)."""
    import json
    from importlib.resources import files
    return json.loads((files("egm") / "data" / "service_jobs.json").read_text(encoding="utf-8"))["jobs"]


def scripted_job(fam: Family, job_id: str) -> bytes:
    """Replay a recorded factory script (e.g. ``ink_discharge_f2``) with this
    family's read key.  Callers must check ``families`` applicability first."""
    job = service_jobs()[job_id]
    return b"".join(esc_pipe(fam, int(op), bytes.fromhex(data)) for op, data in job["steps"])


def color_test_pattern() -> Optional[bytes]:
    try:
        from epson_escp2.epson_encode import EpsonEscp2
        return EpsonEscp2().test_color_pattern()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Delivery
# --------------------------------------------------------------------------- #
def list_queues() -> list[dict]:
    """Installed printer queues: ``{name, port, likely_epson}``."""
    out: list[dict] = []
    if sys.platform == "win32":
        try:
            import win32print  # type: ignore
            for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS, None, 2):
                out.append({"name": p["pPrinterName"], "port": p.get("pPortName", ""),
                            "driver": p.get("pDriverName", ""),
                            "likely_epson": "epson" in (p["pPrinterName"] + p.get("pDriverName", "")).lower()})
        except Exception:
            pass
        return out
    if shutil.which("lpstat"):
        try:
            res = subprocess.run(["lpstat", "-v"], capture_output=True, text=True, timeout=5)
            for line in res.stdout.splitlines():
                m = re.match(r"device for (\S+): (.*)", line.strip())
                if m:
                    name, uri = m.group(1), m.group(2)
                    out.append({"name": name, "port": uri, "driver": "",
                                "likely_epson": "epson" in (name + uri).lower()})
        except Exception:
            pass
    return out


def pick_queue(model_string: str) -> Optional[str]:
    ms = re.sub(r"[^a-z0-9]", "", (model_string or "").lower().replace("series", ""))
    best = None
    for q in list_queues():
        n = re.sub(r"[^a-z0-9]", "", q["name"].lower())
        if ms and ms in n:
            return q["name"]
        if q["likely_epson"] and best is None:
            best = q["name"]
    return best


def send(job: bytes, target: str, job_name: str = "Epson God Mode") -> str:
    """``target``: queue name, ``ip[:port]``, ``/dev/usb/lpN`` or ``file:<path>``."""
    if ENTER_REMOTE in job:
        assert_well_formed(job)
    if target.startswith("file:"):
        p = Path(target[5:])
        p.write_bytes(job)
        return f"saved {len(job)} bytes to {p}"
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}(:\d+)?", target):
        host, _, port = target.partition(":")
        with socket.create_connection((host, int(port or 9100)), timeout=10) as s:
            s.sendall(job)
        return f"sent {len(job)} bytes to {host}:{port or 9100}"
    if target.startswith("/dev/"):
        with open(target, "wb", buffering=0) as f:
            f.write(job)
        return f"wrote {len(job)} bytes to {target}"
    if sys.platform == "win32":
        import win32print  # type: ignore
        h = win32print.OpenPrinter(target)
        try:
            win32print.StartDocPrinter(h, 1, (job_name, None, "RAW"))
            win32print.StartPagePrinter(h)
            win32print.WritePrinter(h, job)
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
        finally:
            win32print.ClosePrinter(h)
        return f"spooled {len(job)} bytes to '{target}' (RAW)"
    if shutil.which("lp"):
        res = subprocess.run(["lp", "-d", target, "-o", "raw", "-t", job_name, "-"], input=job,
                             capture_output=True, timeout=30)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.decode(errors="replace").strip() or "lp failed")
        return f"queued {len(job)} bytes on '{target}': {res.stdout.decode(errors='replace').strip()}"
    raise RuntimeError("no way to deliver a raw print job on this system (need pywin32, CUPS 'lp', a /dev/usb/lp device or an IP)")
