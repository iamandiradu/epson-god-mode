#!/usr/bin/env python3
"""Build egm/data/models.json and egm/data/fatal_codes.json from upstream data.

Sources (all vendored under tools/upstream/, see tools/upstream/README.md):

* devices.xml           -- PrintHelp-style printer database redistributed by
                           CiRIP/ez-reset (AGPL-3.0). Richest source: access
                           keys, waste counters (+ limits), reset sequences,
                           operation counters, fatal error tables, cleaning
                           service codes, serial / head-id addresses, memory
                           ranges.
* reinkpy_epson.toml    -- atufi/reinkpy (AGPL-3.0). Key groups and waste
                           addresses; used to cross-check keys.
* epc_printer_config.py -- Ircama/epson_print_conf (EUPL-1.2). Per-model
                           dividers/verified entries; used to cross-check and
                           to flag models the community verified on hardware.

The output is *data*, so adding/fixing a model never requires touching code.
Run:  python tools/build_models.py
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

HERE = Path(__file__).resolve().parent
UP = HERE / "upstream"
OUT = HERE.parent / "egm" / "data"

# Models we ship "front and centre" in the UI (the user's request + popular ones).
FEATURED = [
    "L3110", "L3111", "L3150", "L3156", "L3160", "L3250", "L3251", "L3260",
    "L1110", "L1210", "L4150", "L4160", "L5190",
    "ET-2700", "ET-2710", "ET-2720", "ET-2750",
    "L3210", "L3211", "L3215", "L3216", "L3252", "L3256", "L1250", "L4260",
    "L5290", "L6190", "L805", "L1800", "L8050", "L18050", "L120", "L121",
    "L380", "L382", "ET-2800", "ET-2850", "ET-4800", "ET-4850", "L310",
]

# Every EcoTank / ink tank model is featured (after the popular list above):
# L-series, ET-series, ET-M and M mono models.
ECOTANK_RE = r"(L\d{3,5}|ET-\d{3,5}|ET-M\d{3,5}|M\d{4})"

# Models whose EEPROM map was verified on real hardware by the community
# (epson_print_conf README / padzero COVERAGE.md) or by us.
COMMUNITY_VERIFIED = {
    "XP-205", "XP-315", "XP-422", "XP-435", "XP-540", "XP-610", "XP-620",
    "XP-700", "XP-760", "XP-830", "XP-850", "XP-960", "XP-2100", "XP-2150",
    "XP-3150", "XP-7100", "ET-2700", "ET-2720", "ET-2750", "ET-2800", "ET-4800",
    "ET-4810", "L355", "L366", "L386", "L3150", "L3250", "L4160", "L405",
    "WF-7525", "Artisan 730",
}
# Verified by this project on real hardware (model -> note).
EGM_VERIFIED: dict[str, str] = {}

# Market variants missing from upstream data, mapped onto the family of the
# model they are a re-badge of. Flagged "alias" so the UI shows the caveat.
ALIASES = {"L3252": "L3250", "L121": "L120"}


def ints(text: str | None) -> list[int]:
    if not text:
        return []
    return [int(t, 0) for t in text.split()]


def pairs(text: str | None) -> dict[str, int]:
    b = ints(text)
    return {str(b[i]): b[i + 1] for i in range(0, len(b) - 1, 2)}


def deobfuscate_key(raw: list[int]) -> str:
    """devices.xml stores the write key shifted by +1 per byte ("Nbsjcbzb")."""
    return "".join(chr(0 if b == 0 else b - 1) for b in raw)


def parse_counter(c: ET.Element) -> dict:
    out: dict = {"addresses": [], "extra": []}
    for e in c.findall("entry"):
        addrs = ints((e.text or "").strip())
        f = e.find("filter")
        if f is not None and len(addrs) == 1:
            parts = (f.text or "").split()
            mask = int(parts[0], 0)
            shift = (mask & -mask).bit_length() - 1 if mask else 0
            out["extra"].append({"address": addrs[0], "mask": mask, "shift": shift,
                                 "raw_filter": " ".join(parts)})
        else:
            out["addresses"] += addrs
    if (c.text or "").strip():
        out["addresses"] += ints(c.text.strip())
    m = c.find("max")
    out["max"] = int(m.text.strip(), 0) if m is not None and m.text and m.text.strip() else None
    mn = c.find("min")
    if mn is not None and mn.text:
        out["min"] = int(mn.text.strip(), 0)
    if not out["extra"]:
        del out["extra"]
    return out


def parse_spec(spec: ET.Element) -> dict:
    d: dict = {}
    svc = spec.find("service")
    if svc is not None:
        fac = svc.find("factory")
        if fac is not None:
            d["read_key"] = ints(fac.text)
        kw = svc.find("keyword")
        if kw is not None:
            d["write_key"] = deobfuscate_key(ints(kw.text))
        for tag in ("readlen", "sendlen"):
            e = svc.find(tag)
            if e is not None:
                d[tag] = int(e.text, 0)
    waste = spec.find("waste")
    if waste is not None:
        q = waste.find("query")
        if q is not None:
            d["waste_counters"] = [parse_counter(c) for c in q.findall("counter")]
        r = waste.find("reset")
        if r is not None:
            d["waste_reset"] = pairs((r.text or "").strip())
            closes = []
            for cl in r.findall("close"):
                closes.append({ch.tag: (ch.text or "").strip() for ch in cl})
            if closes:
                d["waste_reset_close"] = closes
    info = spec.find("information")
    if info is not None:
        rep = info.find("report")
        if rep is not None:
            stats, dates, fatals = [], [], []
            for e in rep:
                name = (e.findtext("name") or "").replace("%-%", "-").replace("%", "").strip()
                name = re.sub(r"\s+", " ", name)
                regs = [ints(r.text) for r in e.findall("registers")]
                if not regs:
                    continue
                if e.tag == "number":
                    stats.append({"name": name, "registers": regs[0] if len(regs) == 1 else regs})
                elif e.tag == "period":
                    dates.append({"name": name, "registers": regs[0]})
                elif e.tag == "fatals":
                    fatals.append({"name": name, "table": (e.findtext("filter") or "").strip(),
                                   "registers": regs[0]})
                elif e.tag == "binary":
                    stats.append({"name": name, "registers": regs[0], "format": "hex"})
            if stats:
                d["stats"] = stats
            if dates:
                d["dates"] = dates
            if fatals:
                d["fatal_registers"] = fatals
    cl = spec.find("cleaning")
    if cl is not None:
        ops = []
        for e in cl:
            ops.append({"kind": e.tag, "name": re.sub(r"\s+", " ", (e.findtext("name") or "").replace("%", "")).strip(),
                        "type": (e.findtext("type") or "").strip(),
                        "data": ints(e.findtext("data"))})
        d["cleaning"] = ops
    ser = spec.find("serial")
    if ser is not None and (ser.text or "").strip():
        d["serial"] = ints(ser.text.strip())
    hid = spec.find("headid")
    if hid is not None and (hid.text or "").strip() and hid.find("hash") is None:
        raw = ints(hid.text.strip())
        # A plain ascending list is a set of EEPROM addresses holding the
        # head id characters; anything else is an encoded spec we only keep raw.
        if raw == sorted(raw) and len(set(raw)) == len(raw):
            d["head_id"] = raw
        else:
            d["head_id_raw"] = raw
    mem = spec.find("memory")
    if mem is not None:
        d["memory"] = {"low": int(mem.findtext("lower"), 0), "high": int(mem.findtext("upper"), 0)}
    for tag in ("usb-id", "net-id"):
        e = spec.find(tag)
        if e is not None and (e.text or "").strip():
            d[tag.replace("-", "_")] = ints(e.text.strip())
    conv = spec.find("conversions")
    if conv is not None:
        extras = []
        for c in conv.findall("conversion"):
            w = c.find("instruction/write")
            if w is None:
                continue
            extras.append({"name": (c.findtext("explanation") or "").replace("%", "").strip(),
                           "description": (c.findtext("description") or "").strip() or None,
                           "write": pairs((w.text or "").strip())})
        if extras:
            d["extra_operations"] = extras
    fat = spec.find("fatals")
    if fat is not None:
        table = {}
        for f in fat.findall("fatal"):
            table[f.findtext("code").strip()] = {"type": f.findtext("type"), "text": (f.findtext("text") or "").strip()}
        d["_fatal_table"] = table
    return d


def coverage(fam: dict) -> str:
    if not fam.get("read_key"):
        return "none"
    if fam.get("waste_counters") and fam.get("waste_reset") and fam.get("write_key"):
        return "full"
    if fam.get("waste_counters") and fam.get("waste_reset"):
        return "partial"
    return "readonly"


def main() -> None:
    root = ET.parse(UP / "devices.xml").getroot()
    devs = {s.tag: s for s in root.find("devices")}
    specs = {k: parse_spec(v) for k, v in devs.items()}
    fatal_tables = {k: v.pop("_fatal_table") for k, v in specs.items() if "_fatal_table" in v}

    families: dict[str, dict] = {}
    models: dict[str, dict] = {}
    for p in root.find("records").findall("printer"):
        if p.get("brand") != "epson" or not p.get("class", "").startswith("epson.printer.dd4"):
            continue
        spec_names = [s.strip() for s in p.get("specs", "").split(",") if s.strip()]
        data_specs = [s for s in spec_names if s in specs and specs[s].get("read_key")]
        if not data_specs:
            continue
        fam_name = data_specs[0]
        if fam_name not in families:
            fam = dict(specs[fam_name])
            fam["fatal_tables"] = [s for s in spec_names if s in fatal_tables]
            fam["coverage"] = coverage(fam)
            fam["models"] = []
            families[fam_name] = fam
        fam = families[fam_name]
        title = p.get("title", "")
        short = p.get("short", "")
        model_string = p.get("model", "")
        # "L3110/L3111" -> ["L3110", "L3111"]; "Epson L3150/L3151/L3156" etc.
        names = [n.strip() for n in re.split(r"[/,]", short) if n.strip()]
        for n in names:
            n = re.sub(r"^Epson\s+", "", n)
            # expand "L3250/51/53" style shorthand
            if names and re.fullmatch(r"\d+", n) and len(n) <= len(names[0]):
                base = re.sub(r"^Epson\s+", "", names[0])
                n = base[: len(base) - len(n)] + n
            models[n] = {
                "family": fam_name,
                "title": title,
                "model_string": model_string,
                "featured": n in FEATURED,
                "verified": ("egm" if n in EGM_VERIFIED else "community" if n in COMMUNITY_VERIFIED else None),
                "verified_note": EGM_VERIFIED.get(n),
            }
            if n not in fam["models"]:
                fam["models"].append(n)

    for alias, target in ALIASES.items():
        if alias not in models and target in models:
            models[alias] = dict(models[target], alias_of=target, featured=alias in FEATURED,
                                 verified=None, verified_note=f"unverified re-badge of {target}")
            families[models[target]["family"]]["models"].append(alias)

    # --- cross-check keys against reinkpy ------------------------------------
    rk = tomllib.loads((UP / "reinkpy_epson.toml").read_text(encoding="utf-8"))
    reink = {}
    for grp in rk.get("EPSON", []):
        for m in grp.get("models", []):
            reink[m] = grp
    mismatches = []
    for name, m in models.items():
        g = reink.get(name)
        if not g or "rkey" not in g:
            continue
        fam = families[m["family"]]
        key = fam.get("read_key") or []
        if key and (key[0] | (key[1] << 8)) != g["rkey"]:
            mismatches.append((name, key, hex(g["rkey"])))
        wk = g.get("wkey1")
        if wk and fam.get("write_key") and fam["write_key"] != wk:
            mismatches.append((name, fam["write_key"], wk))
    if mismatches:
        print("key mismatches vs reinkpy:", mismatches[:10], file=sys.stderr)

    # --- cross-check against epson_print_conf ---------------------------------
    sys.path.insert(0, str(UP))
    from epc_printer_config import PRINTER_CONFIG  # type: ignore
    epc_known = set()
    for k, v in PRINTER_CONFIG.items():
        epc_known.add(k)
        for a in v.get("alias", []):
            epc_known.add(a)
    for name, m in models.items():
        m["in_epson_print_conf"] = name in epc_known

    ecotank = sorted((n for n in models if re.fullmatch(ECOTANK_RE, n)),
                     key=lambda n: (re.sub(r"\d.*", "", n), int(re.sub(r"\D", "", n) or 0), n))
    featured_all = FEATURED + [n for n in ecotank if n not in FEATURED]
    for n, m in models.items():
        m["ecotank"] = n in ecotank
        m["featured"] = n in featured_all
    missing_featured = [f for f in FEATURED if f not in models]
    if missing_featured:
        print("featured models not in database:", missing_featured, file=sys.stderr)

    OUT.mkdir(parents=True, exist_ok=True)
    out = {
        "schema": 1,
        "sources": {
            "devices.xml": "CiRIP/ez-reset (AGPL-3.0-or-later)",
            "reinkpy": "atufi/reinkpy (AGPL-3.0-or-later)",
            "epson_print_conf": "Ircama/epson_print_conf (EUPL-1.2)",
        },
        "popular": FEATURED,
        "featured": featured_all,
        "families": families,
        "models": dict(sorted(models.items())),
    }
    (OUT / "models.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (OUT / "fatal_codes.json").write_text(json.dumps(fatal_tables, indent=1), encoding="utf-8")
    cov = {}
    for f in families.values():
        cov[f["coverage"]] = cov.get(f["coverage"], 0) + len(f["models"])
    print(f"models: {len(models)}  families: {len(families)}  coverage: {cov}")
    print(f"fatal tables: {len(fatal_tables)}")


if __name__ == "__main__":
    main()
