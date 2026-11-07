"""Transport abstraction: anything that can carry an EPSON-CTRL frame.

An EPSON-CTRL frame is ``<2-byte name><le16 length><payload>`` and the printer
answers with an ``@BDC ...`` block.  Three links exist:

* USB (IEEE 1284.4 "D4", socket ``EPSON-CTRL``) -- :mod:`egm.transport.usb`
* SNMP (frame bytes become the tail of an Epson private OID) -- :mod:`egm.transport.snmp`
* Simulator (in-memory printer, for tests and UI work) -- :mod:`egm.transport.sim`
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


class TransportError(RuntimeError):
    """The link is broken or the device vanished."""


@dataclass
class Endpoint:
    """Something the user can pick in a device list."""

    kind: str                     # "usb" | "snmp" | "sim"
    address: str                  # usb path / ip / "sim:<model>"
    label: str                    # human readable
    model_string: str = ""        # MDL from device id, when known up-front
    details: dict = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.kind}:{self.address} ({self.label})"


class ControlLink(Protocol):
    kind: str

    def request(self, frame: bytes, tries: Optional[int] = None) -> Optional[bytes]:
        """Send one EPSON-CTRL frame, return the reply payload (or None)."""

    def describe(self) -> str: ...

    def close(self) -> None: ...

    def print_target(self) -> Optional[str]:
        """Where a raw print job for this printer should go (spooler name or
        ``ip:port``), or None when unknown."""
