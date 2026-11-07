"""EEPROM backups: JSON files written before any write, restorable later."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from . import __version__


def default_dir() -> Path:
    base = os.environ.get("EGM_BACKUP_DIR")
    if base:
        return Path(base)
    home = Path.home()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return root / "EpsonGodMode" / "backups"
    if os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
        return home / "Library" / "Application Support" / "EpsonGodMode" / "backups"
    return Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "epson-god-mode" / "backups"


def save(cells: dict[int, int], *, model: str, family: str, serial: Optional[str], reason: str,
         link: str, directory: Optional[Path] = None, extra: Optional[dict] = None) -> Path:
    d = directory or default_dir()
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_serial = "".join(ch for ch in (serial or "noserial") if ch.isalnum()) or "noserial"
    path = d / f"{model}_{safe_serial}_{stamp}_{reason}.json"
    doc = {
        "app": "epson-god-mode", "version": __version__, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model, "family": family, "serial": serial, "reason": reason, "link": link,
        "cells": {f"0x{a:04X}": v for a, v in sorted(cells.items())},
    }
    if extra:
        doc["extra"] = extra
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path


def load(path: Path | str) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    cells = {int(k, 0): int(v) for k, v in doc.get("cells", {}).items()}
    doc["cells"] = cells
    return doc


def list_backups(directory: Optional[Path] = None) -> list[Path]:
    d = directory or default_dir()
    if not d.exists():
        return []
    return sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
