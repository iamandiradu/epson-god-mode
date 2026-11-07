"""Transport factory: turn an address into an open control link."""
from __future__ import annotations

from typing import Optional

from .base import ControlLink, Endpoint, TransportError


def discover_all(include_sim: bool = True, network: bool = False) -> list[Endpoint]:
    from . import usb
    eps: list[Endpoint] = []
    try:
        eps += usb.discover()
    except Exception:  # pragma: no cover
        pass
    if network:
        from . import snmp
        try:
            eps += snmp.discover()
        except Exception:  # pragma: no cover
            pass
    if include_sim:
        from . import sim
        eps += sim.discover()
    return eps


def open_link(address: Optional[str] = None, kind: Optional[str] = None,
              dry_run: bool = False, **kw) -> ControlLink:
    """``address`` forms: ``None``/``usb`` (first USB printer), ``usb:<path>``,
    ``<ip>`` / ``snmp:<ip>``, ``sim:<MODEL>``."""
    addr = (address or "").strip()
    if kind == "sim" or addr.lower().startswith("sim:"):
        from .sim import SimLink
        name = addr.split(":", 1)[1] if ":" in addr else addr
        return SimLink(name, **{k: v for k, v in kw.items() if k in ("waste_percent", "locked")})
    if kind == "snmp" or addr.lower().startswith("snmp:") or _looks_like_host(addr):
        from .snmp import SnmpLink
        host = addr.split(":", 1)[1] if addr.lower().startswith("snmp:") else addr
        return SnmpLink(host, **{k: v for k, v in kw.items() if k in ("community", "timeout")})
    from .usb import UsbLink
    path = addr.split(":", 1)[1] if addr.lower().startswith("usb:") else (addr or None)
    if path == "usb":
        path = None
    return UsbLink(path, dry_run=dry_run, **{k: v for k, v in kw.items() if k in ("backend", "interface")})


def _looks_like_host(s: str) -> bool:
    import re
    if not s or s.lower() in ("usb", "auto"):
        return False
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", s):
        return True
    return "." in s and "\\" not in s and "/" not in s and not s.startswith("{")


__all__ = ["ControlLink", "Endpoint", "TransportError", "discover_all", "open_link"]
