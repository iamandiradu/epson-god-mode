# Epson God Mode

Open-source waste ink pad resetter, maintenance and adjustment tool for Epson inkjet printers (EcoTank / L-series / ET-series / XP / WF and more). It runs on **Windows, macOS and Linux**, as a desktop app or from the command line.

> **Read this first.** Resetting the waste ink counter does **not** empty the pads. Replace or clean the waste ink pads, or fit an external waste ink tank, before resetting, or ink can leak out of the printer. This project is not affiliated with Seiko Epson Corporation. Use at your own risk.

## What it does

| Area | Features |
|---|---|
| Printer | Auto-detection over USB (and SNMP on the network), manual model override, coverage/verification badges, simulator for any model |
| Status | State and error code, ink levels, warnings, maintenance box, paper counters, serial and firmware |
| Waste ink pads | Read both counters as % of limit, reset with confirmation and automatic backup, read-back verification of every byte, completion-mask step for the L3250/L4260 generation, firmware `rw` temporary reset for locked firmwares |
| Maintenance | Service cleaning levels (gentle → strong) and ink charge over the control channel; nozzle check, head/power cleaning, colour test page, service cleaning, initial ink charge and the F2 ink discharge sequence as print jobs (or saved as `.prn`); model-specific EEPROM operations from the database; first-use date |
| Adjustments | Catalogue of the Adjustment Program items (TOF, head angular, Bi-D, PW/first dot, PE, PF, PF band, paper skew, PF/PW deterioration resets, head ID, shipping setting) with guidance and check-pattern printing; value writes are enabled per model as soon as the EEPROM addresses are verified |
| Counters & errors | Cleaning counters, print/pass/scan counters, ink replacement counters, first-use date, last 5 printer/scanner/general fatal errors decoded, error code lookup across 26 Epson error tables |
| EEPROM | Range dump (hex + ASCII), known-cell or full backups, restore, single-cell read/write, and an **EEPROM diff** tool to discover where an adjustment is stored |
| Model database | 1,500+ model names in ~400 families, with a coverage level per family |

### Coverage levels

* **full** – waste counters, reset sequence and write key known (~990 models, including every model you see in the featured list below).
* **partial** – counters and reset known, write key missing (the printer will likely refuse writes).
* **readonly** – EEPROM readable, no reset data.
* **none** – no EEPROM access data.

Models are additionally marked **verified (community)** when another open-source project confirmed them on hardware, and **verified (egm)** once confirmed by this project.

### Featured models

L3110, L3111, L3150, L3156, L3160, L3210, L3211, L3215, L3216, L3250, L3251, L3252, L3256, L3260, L1110, L1210, L1250, L120, L121, L380, L382, L4150, L4160, L4260, L5190, L5290, L6190, L805, L1800, L8050, L18050, ET-2700, ET-2710, ET-2720, ET-2750, ET-2800, ET-2850, ET-4800, ET-4850, plus every sibling in their families (e.g. L3100–L3119, L3200–L3289, ET-2400/2810 series).

## Quick start

**Windows** – install Python 3.10+ from python.org, then double-click `run_windows.bat`. It creates a local environment and opens the app. USB works through the normal Epson driver (no Zadig/WinUSB needed).

**macOS** – double-click `run_macos.command` (or run it in Terminal). libusb is installed automatically via `libusb-package`; if a printer is not found, `brew install libusb` and try again.

**Linux** – `pip install -e ".[patterns]"`, then `egm gui`. You may need a udev rule or `sudo` for raw USB access.

### Command line

```
egm models                    # featured models (add --all or --search L32)
egm discover [--network]      # find printers
egm info                      # identify, ink levels, waste counters
egm waste                     # waste counters only
egm reset-waste --i-replaced-the-pads [--dry-run]
egm counters                  # usage counters and last fatal errors
egm dump --start 0 --end 0xff # EEPROM hex dump
egm backup [--full] | egm restore FILE
egm clean [LEVEL]             # list/run service cleaning
egm print nozzle-check --queue "EPSON L3110 Series"   # or an IP, or file:out.prn
```

Global options: `-d/--device` (`usb`, `usb:<path>`, `<ip>`, `sim:<MODEL>`), `-m/--model` to force a model, `--dry-run`. Try everything without a printer with `-d sim:L3111`.

Backups are stored in `%LOCALAPPDATA%\EpsonGodMode\backups` (Windows), `~/Library/Application Support/EpsonGodMode/backups` (macOS) or `~/.local/share/epson-god-mode/backups` (Linux).

## Building standalone apps

* Windows: double-click `build_exe.bat` → `dist\EpsonGodMode.exe` (single file, runs without Python) and `dist\egm.exe` (command line). Building needs Python once; running the result does not.
* macOS: double-click `build_mac.command` on a Mac → `dist/Epson God Mode.app` and `dist/EpsonGodMode-macos-<arch>.dmg`.
* CI: `.github/workflows/build.yml` builds Windows, macOS arm64 and macOS Intel on every push.
* Code signing (Windows and macOS): see `docs/SIGNING.md`.

## How it works

The app talks to the printer's **EPSON-CTRL** service. Over USB this goes through IEEE 1284.4 ("D4"), handled by the MIT-licensed [`epson-usb`](https://pypi.org/project/epson-usb/) package (Windows `USBPRINT`, libusb on macOS/Linux). Over the network the same frames are tunnelled through SNMP. EEPROM reads and writes use the `||` factory command with the model's read key and write key; the printer answers `@BDC PS ... EE:AAAAVV;`, `:OK;` or `:NA;`.

Many recent firmwares refuse EEPROM access over the network, and some refuse it entirely after a firmware update. Use USB, and if writes are refused (`:NA;`), try the temporary `rw` reset.

## Adding or fixing a model

All model knowledge is data. Edit the sources in `tools/upstream/` or the overrides in `tools/build_models.py`, run `python tools/build_models.py`, and run `pytest`. To discover the address of an adjustment, use **EEPROM → EEPROM diff**.

## Credits and license

Built on the research of [epson_print_conf](https://github.com/Ircama/epson_print_conf), [reinkpy](https://codeberg.org/atufi/reinkpy), [ez-reset](https://github.com/CiRIP/ez-reset), [padzero](https://github.com/Damnitbran/padzero), [epson-usb](https://pypi.org/project/epson-usb/) and the original [ReInk](https://github.com/lion-simba/reink). Because it includes AGPL-licensed model data, this project is licensed **AGPL-3.0-or-later** (see `LICENSE`).
