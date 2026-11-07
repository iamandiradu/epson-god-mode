"""Command line interface: ``egm <command> [options]`` (``python -m egm``)."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__, APP_NAME
from .modeldb import COVERAGE_LABELS, load as load_db
from .operations import PrinterSession, SafetyError
from .protocol import EepromRefused, ProtocolError
from .transport import TransportError, discover_all


def _session(args) -> PrinterSession:
    return PrinterSession.connect(args.device, args.model, dry_run=args.dry_run)


def _progress(label: str):
    def cb(i, n):
        sys.stderr.write(f"\r{label}: {i}/{n}")
        sys.stderr.flush()
        if i == n:
            sys.stderr.write("\n")
    return cb


def cmd_models(args) -> int:
    db = load_db()
    rows = db.featured() if not args.all else [db.models[n] for n in db.names()]
    if args.search:
        rows = db.search(args.search)
    for m in rows:
        flag = {"egm": "*verified*", "community": "verified(community)"}.get(m.verified or "", "")
        alias = f" (re-badge of {m.alias_of})" if m.alias_of else ""
        print(f"{m.name:<12} family={m.family.name:<8} coverage={m.coverage:<9} mdl='{m.model_string}'{alias} {flag}")
    print(f"\n{len(rows)} models shown ({len(db.models)} in database). Coverage levels:")
    for k, v in COVERAGE_LABELS.items():
        print(f"  {k:<9} {v}")
    return 0


def cmd_discover(args) -> int:
    eps = discover_all(include_sim=args.sim, network=args.network)
    if not eps:
        print("No printers found. USB: check cable/power; network: pass --network or the IP directly.")
        return 1
    for e in eps:
        print(f"{e.kind:<5} {e.address:<60} {e.label}  mdl='{e.model_string}'")
    return 0


def cmd_info(args) -> int:
    with _session(args) as s:
        i = s.info()
        print(f"Model:        {i.model}  (family {i.family}, coverage {i.coverage}"
              f"{', verified: ' + i.verified if i.verified else ''})")
        print(f"Detected:     {'yes, from device id' if i.detected else 'no, model forced by user'}")
        print(f"Device id:    {i.device_id}")
        print(f"Firmware:     {i.firmware}")
        print(f"Serial:       {i.serial}")
        print(f"Link:         {i.link}")
        st = s.status()
        print(f"State:        {st.state}" + (f"  ERROR: {st.error}" if st.error else ""))
        for ink in st.inks:
            print(f"  ink {ink.color:<14} {ink.level_text}")
        if st.warnings:
            print("  warnings: " + "; ".join(st.warnings))
        if s.family.waste_counters and s.family.read_key:
            try:
                for w in s.waste_levels():
                    print(f"Waste {w.index + 1}: {w.text}   {w.name}")
            except EepromRefused as exc:
                print(f"Waste counters: EEPROM access refused -- {exc}")
    return 0


def cmd_status(args) -> int:
    with _session(args) as s:
        st = s.status()
        if args.json:
            print(json.dumps({"state": st.state, "state_code": st.state_code, "error": st.error,
                              "error_code": st.error_code, "warnings": st.warnings,
                              "inks": [vars(i) for i in st.inks], "serial": st.serial,
                              "maintenance_boxes": st.maintenance_boxes, "paper_counts": st.paper_counts,
                              "unknown": [(t, d.hex()) for t, d in st.unknown], "parse_error": st.parse_error}, indent=1))
        else:
            print(f"State: {st.state} ({st.state_code})")
            if st.error:
                print(f"Error: {st.error} ({st.error_code:#x})")
            for ink in st.inks:
                print(f"  {ink.color:<14} {ink.level_text}")
            for w in st.warnings:
                print(f"  warning: {w}")
            if st.parse_error:
                print(f"  (parse note: {st.parse_error})")
    return 0


def cmd_waste(args) -> int:
    with _session(args) as s:
        for w in s.waste_levels():
            print(f"Counter {w.index + 1}: {w.text}   [{', '.join(f'{a:#06x}' for a in w.addresses)}]  {w.name}")
    return 0


def cmd_reset_waste(args) -> int:
    with _session(args) as s:
        before = s.waste_levels()
        for w in before:
            print(f"before: counter {w.index + 1}: {w.text}")
        r = s.reset_waste(acknowledge_pads_replaced=args.i_replaced_the_pads, progress=_progress("writing"))
        print(f"backup: {r.backup_path}")
        for m in r.messages:
            print(m)
        if not r.dry_run:
            for w in s.waste_levels():
                print(f"after:  counter {w.index + 1}: {w.text}")
        print("RESULT:", "OK" if r.ok else "FAILED (see messages; restore from backup if needed)")
        return 0 if r.ok else 2


def cmd_temp_reset(args) -> int:
    with _session(args) as s:
        print(s.temporary_reset())
    return 0


def cmd_counters(args) -> int:
    with _session(args) as s:
        for k, v in s.counters().items():
            print(f"{k:<48} {v}")
    return 0


def cmd_dump(args) -> int:
    with _session(args) as s:
        cells = s.dump(args.start, args.end, progress=_progress("reading"))
        if args.out:
            p = s.backup("manual-dump", cells=cells)
            print(f"saved to {p}" if not args.out or args.out == "-" else "")
            if args.out and args.out != "-":
                Path(args.out).write_text(Path(p).read_text())
                print(f"copied to {args.out}")
        _hexdump(cells)
    return 0


def _hexdump(cells: dict[int, int]) -> None:
    addrs = sorted(cells)
    if not addrs:
        return
    lo, hi = addrs[0] & ~0xF, addrs[-1]
    for base in range(lo, hi + 1, 16):
        row = [cells.get(a) for a in range(base, base + 16)]
        hexs = " ".join("--" if v is None else f"{v:02X}" for v in row)
        asc = "".join("." if v is None or not 32 <= v < 127 else chr(v) for v in row)
        print(f"{base:04X}: {hexs}  {asc}")


def cmd_backup(args) -> int:
    with _session(args) as s:
        p = s.backup("manual", full=args.full, progress=_progress("reading"))
        print(f"backup written: {p}")
    return 0


def cmd_restore(args) -> int:
    with _session(args) as s:
        r = s.restore(args.file, progress=_progress("writing"))
        print(f"pre-restore backup: {r.backup_path}")
        for m in r.messages:
            print(m)
        print("RESULT:", "OK" if r.ok else "FAILED")
        return 0 if r.ok else 2


def cmd_read(args) -> int:
    with _session(args) as s:
        for a in args.addr:
            addr = int(a, 0)
            print(f"{addr:#06x} = {s.read(addr):#04x}")
    return 0


def cmd_write(args) -> int:
    cells = {}
    for item in args.assign:
        a, _, v = item.partition("=")
        cells[int(a, 0)] = int(v, 0)
    with _session(args) as s:
        r = s.write_cells(cells, reason="manual-write", progress=_progress("writing"))
        print(f"backup: {r.backup_path}")
        for m in r.messages:
            print(m)
        print("RESULT:", "OK" if r.ok else "FAILED")
        return 0 if r.ok else 2


def cmd_clean(args) -> int:
    with _session(args) as s:
        opts = s.cleaning_options()
        if args.level is None:
            for i, o in enumerate(opts):
                print(f"{i}: {o['name']}  (service data {bytes(o['data']).hex()})")
            return 0
        target = None if args.no_fallback else (args.queue or "direct")
        print(s.run_cleaning(args.level, target))
    return 0


def cmd_print(args) -> int:
    from . import printjobs as pj
    db = load_db()
    fam = db.get(args.model).family if args.model else None
    if args.job == "nozzle-check":
        job = pj.nozzle_check()
    elif args.job == "release":
        job = pj.release_stuck_job()
    elif args.job == "head-clean":
        job = pj.head_cleaning(power=False)
    elif args.job == "power-clean":
        job = pj.head_cleaning(power=True)
    elif args.job == "color-test":
        job = pj.color_test_pattern()
        if job is None:
            print("epson-escp2 (with Pillow) is needed for the colour test pattern")
            return 1
    elif args.job in ("service-clean", "ink-charge", "discharge"):
        if fam is None:
            print("--model is required for factory jobs (or connect, so it is detected)")
            return 1
        if args.job == "service-clean":
            job = pj.service_cleaning_job(fam, args.level or 2)
        elif args.job == "ink-charge":
            job = pj.ink_charge_job(fam)
        else:
            jd = pj.service_jobs()["ink_discharge_f2"]
            if fam.name not in jd["families"] and not args.force:
                print(f"discharge script is only known for families {jd['families']}; use --force to override")
                return 1
            job = pj.scripted_job(fam, "ink_discharge_f2")
    else:
        print("unknown job")
        return 1
    if args.queue:
        print(pj.send(job, args.queue))
        return 0
    # default: straight to the connected printer (USB pipe / port 9100), no print queue
    with _session(args) as s:
        print(s.print_job(job, "direct"))
    return 0


def cmd_gui(args) -> int:
    from .gui.app import run
    return run(sys.argv[2:])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="egm", description=f"{APP_NAME} {__version__} -- Epson maintenance, reset and adjustment tool")
    p.add_argument("-d", "--device", help="usb (default: first Epson USB printer), usb:<path>, <ip>, or sim:<MODEL>")
    p.add_argument("-m", "--model", help="force the printer model (otherwise auto-detected)")
    p.add_argument("--dry-run", action="store_true", help="never write to the printer; log what would be written")
    p.add_argument("-v", "--verbose", action="store_true")
    # the same options are accepted after the sub-command too
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-d", "--device", dest="device", default=argparse.SUPPRESS)
    common.add_argument("-m", "--model", dest="model", default=argparse.SUPPRESS)
    common.add_argument("--dry-run", dest="dry_run", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("-v", "--verbose", dest="verbose", action="store_true", default=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)  # type: ignore[method-assign]

    sp = sub.add_parser("models", help="list supported models"); sp.add_argument("--all", action="store_true"); sp.add_argument("--search")
    sp.set_defaults(fn=cmd_models)
    sp = sub.add_parser("discover", help="find connected printers"); sp.add_argument("--network", action="store_true"); sp.add_argument("--sim", action="store_true")
    sp.set_defaults(fn=cmd_discover)
    sub.add_parser("info", help="identify the printer and show ink/waste summary").set_defaults(fn=cmd_info)
    sp = sub.add_parser("status", help="printer status block"); sp.add_argument("--json", action="store_true"); sp.set_defaults(fn=cmd_status)
    sub.add_parser("waste", help="waste ink counters").set_defaults(fn=cmd_waste)
    sp = sub.add_parser("reset-waste", help="reset the waste ink counters (after servicing the pads!)")
    sp.add_argument("--i-replaced-the-pads", action="store_true", help="required acknowledgement")
    sp.set_defaults(fn=cmd_reset_waste)
    sub.add_parser("temp-reset", help="firmware 'rw' temporary reset (locked firmwares)").set_defaults(fn=cmd_temp_reset)
    sub.add_parser("counters", help="operation counters, dates, last fatal errors").set_defaults(fn=cmd_counters)
    sp = sub.add_parser("dump", help="hex dump of the EEPROM"); sp.add_argument("--start", type=lambda x: int(x, 0)); sp.add_argument("--end", type=lambda x: int(x, 0)); sp.add_argument("--out")
    sp.set_defaults(fn=cmd_dump)
    sp = sub.add_parser("backup", help="save EEPROM cells to a JSON backup"); sp.add_argument("--full", action="store_true", help="whole EEPROM range, not just known cells")
    sp.set_defaults(fn=cmd_backup)
    sp = sub.add_parser("restore", help="write a backup back"); sp.add_argument("file"); sp.set_defaults(fn=cmd_restore)
    sp = sub.add_parser("read", help="read EEPROM addresses"); sp.add_argument("addr", nargs="+"); sp.set_defaults(fn=cmd_read)
    sp = sub.add_parser("write", help="write EEPROM cells, e.g. 0x30=0 0x31=0"); sp.add_argument("assign", nargs="+"); sp.set_defaults(fn=cmd_write)
    sp = sub.add_parser("clean", help="service cleaning / ink charge (control channel, print-job fallback)"); sp.add_argument("level", nargs="?", type=int)
    sp.add_argument("--queue", help="print queue/IP/file: used when the control channel refuses"); sp.add_argument("--no-fallback", action="store_true")
    sp.set_defaults(fn=cmd_clean)
    sp = sub.add_parser("print", help="send a maintenance print job")
    sp.add_argument("job", choices=["nozzle-check", "release", "head-clean", "power-clean", "color-test", "service-clean", "ink-charge", "discharge"])
    sp.add_argument("--queue", help="instead of printing directly: a print queue name, ip[:port], /dev/usb/lpN or file:<path>")
    sp.add_argument("--level", type=int); sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_print)
    sub.add_parser("gui", help="start the graphical interface").set_defaults(fn=cmd_gui)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        return args.fn(args) or 0
    except SafetyError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    except EepromRefused as exc:
        print(f"PRINTER REFUSED: {exc}", file=sys.stderr)
        return 4
    except (ProtocolError, TransportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 5
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
