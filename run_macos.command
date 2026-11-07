#!/usr/bin/env bash
# Quick start on macOS without building (double-click in Finder, or run in Terminal).
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -e ".[patterns,macos]"
fi
export EPSON_USB_LIBUSB="${EPSON_USB_LIBUSB:-$(.venv/bin/python -c 'import libusb_package;print(libusb_package.get_library_path() or "")' 2>/dev/null)}"
if [ $# -eq 0 ]; then .venv/bin/python -m egm gui; else .venv/bin/python -m egm "$@"; fi
