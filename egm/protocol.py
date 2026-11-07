"""EPSON-CTRL protocol: frames, EEPROM access and the ``@BDC ST2`` status block.

Everything here is transport-agnostic; a :class:`egm.transport.base.ControlLink`
carries the bytes.  Model-specific facts (keys, address width) come from a
:class:`egm.modeldb.Family`.

Frame layout (service manual LX-300+II, reproduced by every open resetter)::

    read  : 7C 7C <len16> <r1> <r2> 41 BE A0 <addr lo> [<addr hi>]
    write : 7C 7C <len16> <r1> <r2> 42 BD 21 <addr lo> [<addr hi>] <value> <wkey x8>
    reply : 00 @BDC PS \\r\\n EE:AAAAVV; 0C      (AAAA address, VV value)
            00 @BDC PS \\r\\n ||:OK; 0C           (write accepted)
            00 @BDC PS \\r\\n ||:NA; 0C           (refused: wrong key / locked firmware)
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Optional

from .modeldb import Family
from .transport.base import ControlLink

READ_OP = ord("A")
WRITE_OP = ord("B")
SERVICE_OP = 0x84      # cleaning / ink charge (devices.xml: dd4_command_clean_basic)


class ProtocolError(RuntimeError):
    pass


class EepromRefused(ProtocolError):
    """The printer answered ``:NA;`` -- wrong key or firmware-locked EEPROM."""


# --------------------------------------------------------------------------- #
#  Frame builders
# --------------------------------------------------------------------------- #
def frame(name: bytes | str, payload: bytes = b"") -> bytes:
    if isinstance(name, str):
        name = name.encode("ascii")
    assert len(name) == 2
    return name + struct.pack("<H", len(payload)) + payload


def opcode(letter: int) -> bytes:
    return bytes([letter & 0xFF, ~letter & 0xFF, ((letter >> 1) & 0x7F) | ((letter << 7) & 0x80)])


def addr_bytes(addr: int, width: int) -> bytes:
    if width == 1:
        if not 0 <= addr <= 0xFF:
            raise ValueError(f"address {addr:#x} does not fit a 1-byte model")
        return bytes([addr])
    return struct.pack("<H", addr)


def eeprom_read_frame(fam: Family, addr: int) -> bytes:
    rk = bytes(fam.read_key[:2])
    return frame(b"||", rk + opcode(READ_OP) + addr_bytes(addr, fam.sendlen))


def eeprom_write_frame(fam: Family, addr: int, value: int) -> bytes:
    rk = bytes(fam.read_key[:2])
    wk = fam.wire_write_key or b""
    return frame(b"||", rk + opcode(WRITE_OP) + addr_bytes(addr, fam.sendlen) + bytes([value & 0xFF]) + wk)


def service_frame(fam: Family, data: bytes) -> bytes:
    """Factory service command (cleaning levels, ink charge)."""
    rk = bytes(fam.read_key[:2])
    return frame(b"||", rk + opcode(SERVICE_OP) + data)


_EE_RE = re.compile(rb"EE:([0-9A-Fa-f]{4,6});")


def parse_eeprom_reply(reply: Optional[bytes], readlen: int) -> Optional[tuple[int, int]]:
    if not reply:
        return None
    m = _EE_RE.search(reply)
    if not m:
        return None
    hexs = m.group(1).decode()
    if readlen == 1 and len(hexs) == 4:
        return int(hexs[:2], 16), int(hexs[2:], 16)
    if len(hexs) == 6:
        return int(hexs[:4], 16), int(hexs[4:], 16)
    # tolerate the other width
    if len(hexs) == 4:
        return int(hexs[:2], 16), int(hexs[2:], 16)
    return None


def is_refused(reply: Optional[bytes]) -> bool:
    return bool(reply) and b":NA;" in reply


def is_ok(reply: Optional[bytes]) -> bool:
    return bool(reply) and b":OK;" in reply


# --------------------------------------------------------------------------- #
#  Status block
# --------------------------------------------------------------------------- #
CARTRIDGE_NAMES = {0x01: "Black", 0x03: "Cyan", 0x04: "Magenta", 0x05: "Yellow", 0x06: "Light Cyan",
                   0x07: "Light Magenta", 0x0A: "Light Black", 0x0B: "Matte Black",
                   0x0F: "Light Light Black", 0x10: "Orange", 0x11: "Green"}
INK_COLORS = {0x00: "Black", 0x01: "Cyan", 0x02: "Magenta", 0x03: "Yellow", 0x04: "Light Cyan",
              0x05: "Light Magenta", 0x06: "Dark Yellow", 0x07: "Grey", 0x08: "Light Black",
              0x09: "Red", 0x0A: "Blue", 0x0B: "Gloss Optimizer", 0x0C: "Light Grey", 0x0D: "Orange"}
STATES = {0x00: "Error", 0x01: "Self printing", 0x02: "Busy", 0x03: "Waiting / printing",
          0x04: "Ready", 0x05: "Paused", 0x06: "Ink drying", 0x07: "Cleaning",
          0x08: "Factory shipment (not initialised)", 0x09: "Motor drive off", 0x0A: "Shutdown",
          0x0B: "Waiting for paper initialisation", 0x0C: "Initialising paper", 0x0F: "Nozzle check",
          0x11: "Charging ink"}
ERRORS = {0x00: "Fatal error", 0x01: "Other interface selected", 0x02: "Cover open", 0x04: "Paper jam",
          0x05: "Ink out", 0x06: "Paper out", 0x0A: "Paper size error", 0x0C: "Paper size/type/path error",
          0x10: "Waste ink pad counter overflow (service required)", 0x11: "Wait return from tear-off",
          0x12: "Double feed", 0x1A: "Cartridge cover open", 0x1C: "Cutter error", 0x1D: "Cutter jam",
          0x22: "Maintenance box missing", 0x25: "Rear cover open", 0x29: "CD-R tray out",
          0x2A: "Memory card loading error", 0x2B: "Tray cover open", 0x2C: "Ink cartridge overflow",
          0x33: "Initial ink fill impossible", 0x36: "Maintenance box cover open",
          0x37: "Scanner or front cover open", 0x41: "Maintenance request", 0x47: "Printing disabled",
          0x4A: "Maintenance box near end", 0x4B: "Driver mismatch"}
WARNINGS = {0x10: "Ink low (Black or Yellow)", 0x11: "Ink low (Magenta)", 0x12: "Ink low (Yellow or Cyan)",
            0x13: "Ink low (Cyan or Matte Black)", 0x14: "Ink low (Photo Black)", 0x15: "Ink low (Red)",
            0x16: "Ink low (Blue)", 0x17: "Ink low (Gloss optimizer)", 0x44: "Black print mode",
            0x51: "Cleaning disabled (Cyan)", 0x52: "Cleaning disabled (Magenta)",
            0x53: "Cleaning disabled (Yellow)", 0x54: "Cleaning disabled (Black)"}


@dataclass
class InkLevel:
    cartridge: str
    color: str
    level: int   # 0-100, or special (>100 -> unknown/missing)

    @property
    def level_text(self) -> str:
        if self.level == 110:
            return "missing"
        if self.level == 105:
            return "unknown"
        if 0 <= self.level <= 100:
            return f"{self.level}%"
        return f"raw {self.level}"


@dataclass
class PrinterStatus:
    raw: bytes = b""
    state_code: Optional[int] = None
    state: str = "unknown"
    error_code: Optional[int] = None
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    inks: list[InkLevel] = field(default_factory=list)
    serial: Optional[str] = None
    maintenance_boxes: list[str] = field(default_factory=list)
    paper_counts: dict = field(default_factory=dict)
    ink_replacement_counter: dict = field(default_factory=dict)
    unknown: list[tuple[int, bytes]] = field(default_factory=list)
    parse_error: Optional[str] = None

    @property
    def ready(self) -> bool:
        return self.state_code in (0x03, 0x04)

    @property
    def waste_overflow(self) -> bool:
        return self.error_code == 0x10


def parse_status(data: Optional[bytes]) -> PrinterStatus:
    st = PrinterStatus(raw=data or b"")
    if not data or len(data) < 13:
        st.parse_error = "no / short status reply"
        return st
    if data[:11] != b"\x00@BDC ST2\r\n":
        i = data.find(b"BDC ST2\r\n")
        if i < 0:
            st.parse_error = "not a BDC ST2 block"
            return st
        data = b"\x00@" + data[i:]
    declared = struct.unpack("<H", data[11:13])[0]
    buf = data[13:]
    if len(buf) != declared:
        st.parse_error = f"length mismatch ({len(buf)} vs {declared})"
    pos = 0
    while pos + 2 <= len(buf):
        ftype, ln = buf[pos], buf[pos + 1]
        pos += 2
        item = buf[pos:pos + ln]
        pos += ln
        if len(item) != ln:
            st.parse_error = "truncated element"
            break
        if ftype == 0x01 and item:
            st.state_code = item[0]
            st.state = STATES.get(item[0], f"unknown ({item[0]:#x})")
        elif ftype == 0x02 and item:
            st.error_code = item[0]
            st.error = ERRORS.get(item[0], f"unknown error ({item[0]:#x})")
        elif ftype == 0x04:
            st.warnings = [WARNINGS.get(b, f"unknown warning ({b:#x})") for b in item]
        elif ftype == 0x0F and item:
            size = item[0]
            off = 1
            while off + 2 < len(item) + 1 and size >= 3:
                c, ic, lvl = item[off], item[off + 1], item[off + 2]
                st.inks.append(InkLevel(CARTRIDGE_NAMES.get(c, f"0x{c:02X}"), INK_COLORS.get(ic, f"0x{ic:02X}"), lvl))
                off += size
        elif ftype == 0x1F:
            st.serial = item.decode("ascii", "replace").strip("\x00")
        elif ftype == 0x40 and not st.serial:
            st.serial = item.decode("ascii", "replace").strip("\x00")
        elif ftype == 0x36 and ln == 20:
            keys = ["normal", "page", "color", "monochrome", "blank"]
            st.paper_counts = {k: int.from_bytes(item[i * 4:(i + 1) * 4], "little", signed=True)
                               for i, k in enumerate(keys)}
        elif ftype == 0x37 and item:
            n = item[0]
            if 1 <= n <= 2:
                for i in range(1, ln, n):
                    v = item[i]
                    st.maintenance_boxes.append({0: "not full", 1: "near full", 2: "full"}.get(v, f"unknown ({v})"))
        elif ftype == 0x45 and ln == 4:
            st.ink_replacement_counter = {"Black": item[0], "Cyan": item[1], "Magenta": item[2], "Yellow": item[3]}
        else:
            st.unknown.append((ftype, item))
    return st


# --------------------------------------------------------------------------- #
#  Session helper
# --------------------------------------------------------------------------- #
class EpsonCtrl:
    """Typed commands over a control link for one printer family."""

    def __init__(self, link: ControlLink, family: Family):
        self.link = link
        self.family = family

    # -- generic -------------------------------------------------------------
    def command(self, name: str, payload: bytes = b"") -> Optional[bytes]:
        return self.link.request(frame(name, payload))

    def status(self) -> PrinterStatus:
        return parse_status(self.command("st", b"\x01"))

    def device_id(self) -> str:
        r = self.command("di", b"\x01") or b""
        txt = r.decode("latin-1", "replace")
        m = re.search(r"(MFG:.*?;)(?:\x0c|$)", txt, re.S)
        return (m.group(1) if m else txt).strip("\x00\x0c\r\n ")

    def firmware_version(self) -> Optional[str]:
        r = self.command("vi", b"\x00") or b""
        m = re.search(rb"vi:00:([0-9A-Za-z]{6})", r)
        return m.group(1).decode() if m else None

    def cartridge_types(self) -> Optional[str]:
        r = self.command("ia", b"\x00") or b""
        m = re.search(rb"IA:00;([^;]*);", r)
        return m.group(1).decode("latin-1") if m else None

    # -- EEPROM ------------------------------------------------------------------
    def read(self, addr: int) -> int:
        if not self.family.read_key:
            raise ProtocolError(f"family {self.family.name} has no read key")
        reply = self.link.request(eeprom_read_frame(self.family, addr))
        if is_refused(reply):
            raise EepromRefused(f"EEPROM read at {addr:#06x} refused (:NA;) -- wrong model/key or firmware lock")
        parsed = parse_eeprom_reply(reply, self.family.readlen)
        if not parsed:
            raise ProtocolError(f"unparseable EEPROM reply for {addr:#06x}: {reply!r}")
        got_addr, value = parsed
        if got_addr != addr and (got_addr & 0xFF) != (addr & 0xFF):
            raise ProtocolError(f"printer answered address {got_addr:#06x} for {addr:#06x}")
        return value

    def read_many(self, addrs, progress=None) -> dict[int, int]:
        out: dict[int, int] = {}
        addrs = list(addrs)
        for i, a in enumerate(addrs):
            out[a] = self.read(a)
            if progress:
                progress(i + 1, len(addrs))
        return out

    def write(self, addr: int, value: int, verify: bool = True) -> None:
        if not self.family.can_write:
            raise ProtocolError(f"family {self.family.name} has no write key; refusing to write")
        reply = self.link.request(eeprom_write_frame(self.family, addr, value))
        if is_refused(reply) or not is_ok(reply):
            raise EepromRefused(f"EEPROM write at {addr:#06x} refused: {reply!r}")
        if verify:
            back = self.read(addr)
            if back != (value & 0xFF):
                raise ProtocolError(f"verify failed at {addr:#06x}: wrote {value:#04x}, read {back:#04x}")

    # -- service -----------------------------------------------------------------
    def service(self, data: bytes) -> Optional[bytes]:
        return self.link.request(service_frame(self.family, data))

    def rw_reset(self, serial: str, mode: int = 1) -> Optional[bytes]:
        """``rw`` -- firmware-side temporary waste reset keyed by the serial
        number (works on some locked firmwares)."""
        import hashlib
        digest = hashlib.sha1(serial.encode("ascii")).digest()
        return self.command("rw", struct.pack("<H", mode) + digest)
