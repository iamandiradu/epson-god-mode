"""Network link: EPSON-CTRL frames tunnelled through SNMPv1 GET.

Epson network printers expose a private OID family under
``1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1``; the bytes of an EPSON-CTRL frame are
appended as sub-identifiers and the printer answers with the ``@BDC`` block as
an OctetString.  A tiny BER encoder/decoder is all that is needed, so there is
no SNMP library dependency.

Caveat (see README): many recent firmwares refuse EEPROM access over the
network (``:NA;`` for every ``||`` request).  Status, serial and ink levels
still work; for resets those printers must be connected over USB.
"""
from __future__ import annotations

import socket
import struct
from typing import Optional

from .base import Endpoint, TransportError

EPSON_CTRL_OID = "1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1"

# Standard MIB-II / Printer MIB bits that are useful for identification.
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_HR_DEVICE_DESCR = "1.3.6.1.2.1.25.3.2.1.3.1"
OID_PRT_SERIAL = "1.3.6.1.2.1.43.5.1.1.17.1"
OID_IEEE1284_ID = "1.3.6.1.4.1.1248.1.1.3.1.1.6.0"   # Epson private: device id string
OID_EPSON_MODEL = "1.3.6.1.4.1.1248.1.2.2.1.1.1.2.1"  # Epson private: model name


# --------------------------------------------------------------------------- #
#  Minimal BER
# --------------------------------------------------------------------------- #
def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag: int, body: bytes) -> bytes:
    return bytes([tag]) + _len(len(body)) + body


def _int(v: int) -> bytes:
    if v == 0:
        return _tlv(0x02, b"\x00")
    b = v.to_bytes((v.bit_length() + 8) // 8, "big", signed=True)
    return _tlv(0x02, b)


def _oid(text: str) -> bytes:
    parts = [int(p) for p in text.split(".") if p != ""]
    body = bytes([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        if p < 0x80:
            body += bytes([p])
        else:
            chunks = []
            while p:
                chunks.insert(0, p & 0x7F)
                p >>= 7
            body += bytes([c | 0x80 for c in chunks[:-1]] + [chunks[-1]])
    return _tlv(0x06, body)


def _read_tlv(buf: bytes, pos: int) -> tuple[int, bytes, int]:
    tag = buf[pos]
    pos += 1
    ln = buf[pos]
    pos += 1
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(buf[pos:pos + n], "big")
        pos += n
    return tag, buf[pos:pos + ln], pos + ln


def build_get(oid: str, community: str, request_id: int) -> bytes:
    varbind = _tlv(0x30, _oid(oid) + b"\x05\x00")
    pdu = _tlv(0xA0, _int(request_id) + _int(0) + _int(0) + _tlv(0x30, varbind))
    return _tlv(0x30, _int(0) + _tlv(0x04, community.encode()) + pdu)


def parse_get_response(data: bytes) -> tuple[int, Optional[bytes]]:
    """Return ``(error_status, value_bytes)`` of the first varbind."""
    tag, msg, _ = _read_tlv(data, 0)
    pos = 0
    _, _ver, pos = _read_tlv(msg, pos)
    _, _comm, pos = _read_tlv(msg, pos)
    pdu_tag, pdu, _ = _read_tlv(msg, pos)
    pos = 0
    _, _rid, pos = _read_tlv(pdu, pos)
    _, err, pos = _read_tlv(pdu, pos)
    _, _idx, pos = _read_tlv(pdu, pos)
    _, vbl, _ = _read_tlv(pdu, pos)
    _, vb, _ = _read_tlv(vbl, 0)
    _, _o, p2 = _read_tlv(vb, 0)
    vtag, value, _ = _read_tlv(vb, p2)
    error_status = int.from_bytes(err, "big", signed=True) if err else 0
    if vtag in (0x80, 0x81, 0x82, 0x05):  # noSuchObject / noSuchInstance / endOfMib / null
        return error_status, None
    return error_status, value


class SnmpLink:
    kind = "snmp"

    def __init__(self, host: str, community: str = "public", timeout: float = 3.0, port: int = 161):
        self.host = host
        self.port = port
        self.community = community
        self.timeout = timeout
        self._rid = 1
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(timeout)

    def get(self, oid: str, tries: int = 2) -> Optional[bytes]:
        last: Optional[Exception] = None
        for _ in range(max(1, tries)):
            self._rid = (self._rid + 1) & 0x7FFFFFFF
            pkt = build_get(oid, self.community, self._rid)
            try:
                self._sock.sendto(pkt, (self.host, self.port))
                data, _ = self._sock.recvfrom(65535)
                err, value = parse_get_response(data)
                if err:
                    return None
                return value
            except socket.timeout as exc:
                last = exc
                continue
            except OSError as exc:
                raise TransportError(f"SNMP to {self.host}: {exc}") from exc
        if last:
            raise TransportError(f"SNMP to {self.host}: no answer ({last})")
        return None

    def get_str(self, oid: str) -> Optional[str]:
        v = self.get(oid)
        return v.decode("latin-1").strip("\x00 ") if v is not None else None

    # -- ControlLink ---------------------------------------------------------
    def request(self, frame: bytes, tries: Optional[int] = None) -> Optional[bytes]:
        oid = EPSON_CTRL_OID + "." + ".".join(str(b) for b in frame)
        return self.get(oid, tries=tries or 2)

    def describe(self) -> str:
        return f"SNMP {self.host}"

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:  # pragma: no cover
            pass

    def print_target(self) -> Optional[str]:
        return "direct"

    def print_raw(self, job: bytes) -> str:
        """Raw job to the printer's port 9100 (no print queue)."""
        with socket.create_connection((self.host, 9100), timeout=10) as s:
            s.sendall(job)
        return f"sent {len(job)} bytes to {self.host}:9100"

    # -- identification --------------------------------------------------------
    def device_id(self) -> str:
        return self.get_str(OID_IEEE1284_ID) or ""

    def model_string(self) -> str:
        for oid in (OID_EPSON_MODEL, OID_HR_DEVICE_DESCR, OID_SYS_DESCR):
            s = self.get_str(oid)
            if s:
                return s.replace("EPSON", "").strip()
        return ""


def probe(host: str, community: str = "public", timeout: float = 1.5) -> Optional[Endpoint]:
    """Return an Endpoint if ``host`` answers SNMP like an Epson printer."""
    link = SnmpLink(host, community, timeout)
    try:
        did = link.device_id()
        model = ""
        if did:
            import re
            m = re.search(r"MDL:([^;]+);", did)
            model = m.group(1).strip() if m else ""
        if not model:
            model = link.model_string()
        if not model and not did:
            return None
        return Endpoint(kind="snmp", address=host, label=f"{model or 'Epson'} @ {host}",
                        model_string=model, details={"device_id": did})
    except TransportError:
        return None
    finally:
        link.close()


def discover(subnet_hint: Optional[str] = None, timeout: float = 1.0) -> list[Endpoint]:
    """Best-effort LAN discovery: SNMP GET to the local /24 broadcast address.

    Printers answer a broadcast sysDescr request; each responder is then probed
    individually.  Quiet networks simply return an empty list.
    """
    found: list[Endpoint] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(timeout)
        target = subnet_hint or "255.255.255.255"
        s.sendto(build_get(OID_SYS_DESCR, "public", 4242), (target, 161))
        responders: set[str] = set()
        import time
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, (ip, _) = s.recvfrom(65535)
            except socket.timeout:
                break
            try:
                _, v = parse_get_response(data)
            except Exception:
                continue
            if v and b"EPSON" in v.upper():
                responders.add(ip)
        s.close()
        for ip in sorted(responders):
            ep = probe(ip)
            if ep:
                found.append(ep)
    except OSError:
        pass
    return found
