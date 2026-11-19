"""Troubleshooting knowledge base: per-series panel guides + symptom guides.

Data: ``egm/data/troubleshooting.json`` (built by ``tools/build_troubleshooting.py``).
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Optional

PROCEDURE_LABELS = {"nozzle_check": "Nozzle check", "head_cleaning": "Head cleaning",
                    "power_cleaning": "Power cleaning"}


@dataclass
class Profile:
    """What we know about one printer for troubleshooting."""
    key: str                 # series key, or "generic"
    name: str
    data: dict
    exact: bool              # True if the model is listed in that series

    def procedure(self, name: str) -> str:
        return self.data.get("procedures", {}).get(name, "")

    def fill(self, text: str) -> str:
        """Replace {nozzle_check}-style tokens with this profile's procedures."""
        def sub(m):
            p = self.procedure(m.group(1))
            return p if p else m.group(0)
        return re.sub(r"\{(nozzle_check|head_cleaning|power_cleaning)\}", sub, text)


class KnowledgeBase:
    def __init__(self, doc: dict):
        self.doc = doc
        self.series: dict[str, dict] = doc["series"]
        self.guides: list[dict] = doc["guides"]
        self.generic: dict[str, dict] = doc["generic"]
        self._by_model = {m.upper(): k for k, s in self.series.items() for m in s["models"]}

    # -- lookup ------------------------------------------------------------------
    def profile(self, model: Optional[str]) -> Profile:
        """Series profile for a model name; generic fallback otherwise."""
        if model:
            key = self._by_model.get(model.strip().upper())
            if key is None:
                try:  # aliases from the model database (e.g. re-badges)
                    from .modeldb import load
                    m = load().get(model)
                    if m and m.alias_of:
                        key = self._by_model.get(m.alias_of.upper())
                except Exception:  # pragma: no cover
                    pass
            if key:
                s = self.series[key]
                return Profile(key, s["name"], s, True)
        g = dict(self.generic["buttons"])
        g["lcd_codes"] = self.generic["lcd"]["lcd_codes"]
        return Profile("generic", "Generic Epson ink tank printer", g, False)

    def series_choices(self) -> list[tuple[str, str]]:
        return [(k, s["name"]) for k, s in self.series.items()]

    def profile_for_series(self, key: str) -> Profile:
        if key in self.series:
            return Profile(key, self.series[key]["name"], self.series[key], True)
        return self.profile(None)

    def guide(self, gid: str) -> Optional[dict]:
        return next((g for g in self.guides if g["id"] == gid), None)

    def categories(self) -> list[str]:
        out: list[str] = []
        for g in self.guides:
            if g["category"] not in out:
                out.append(g["category"])
        return out

    def search(self, query: str) -> list[dict]:
        """Guides ranked by how well they match ``query`` (title > symptoms > text)."""
        words = [w for w in re.findall(r"[a-z0-9:;\-]+", query.lower()) if len(w) > 1]
        if not words:
            return list(self.guides)
        scored = []
        for g in self.guides:
            title = g["title"].lower()
            sym = " ".join(g["symptoms"]).lower()
            body = " ".join(s["title"] + " " + s["text"] for s in g["steps"]).lower()
            score = sum(5 * (w in title) + 3 * (w in sym) + (w in body) for w in words)
            if score:
                scored.append((score, g))
        scored.sort(key=lambda t: -t[0])
        return [g for _, g in scored]

    def light_matches(self, profile: Profile, query: str) -> list[dict]:
        """Light patterns / LCD codes of a profile mentioning the query words."""
        words = [w for w in re.findall(r"[a-z0-9\-]+", query.lower()) if len(w) > 1]
        rows = profile.data.get("lights", []) + profile.data.get("lcd_codes", [])
        if not words:
            return []
        return [r for r in rows if all(w in (r["pattern"] + " " + r["meaning"]).lower() for w in words)]


@lru_cache(maxsize=1)
def load() -> KnowledgeBase:
    doc = json.loads((files("egm") / "data" / "troubleshooting.json").read_text(encoding="utf-8"))
    return KnowledgeBase(doc)


# --------------------------------------------------------------------------- #
#  Rendering (HTML for the GUI, plain text for the CLI)
# --------------------------------------------------------------------------- #
def _e(s: str) -> str:
    return html.escape(s or "")


def _table(rows: list[dict], head: str) -> str:
    if not rows:
        return ""
    trs = "".join(f"<tr><td><b>{_e(r['pattern'])}</b></td><td>{_e(r['meaning'])}</td><td>{_e(r['action'])}</td></tr>"
                  for r in rows)
    return (f"<h3>{head}</h3><table border='0' cellspacing='0' cellpadding='4' width='100%'>"
            f"<tr><th align='left'>Pattern</th><th align='left'>Meaning</th><th align='left'>What to do</th></tr>{trs}</table>")


def _sources(urls: list[str]) -> str:
    if not urls:
        return ""
    return "<p><small>Sources: " + " · ".join(f"<a href='{_e(u)}'>{i + 1}</a>" for i, u in enumerate(urls)) + "</small></p>"


def profile_html(p: Profile, model: Optional[str] = None) -> str:
    d = p.data
    head = f"<h2>{_e(p.name)}</h2>"
    if model and not p.exact:
        head += (f"<p><i>{_e(model)} isn't in the per-series database yet, so this is the generic guidance. "
                 "Check your model's Epson user guide for its exact light patterns.</i></p>")
    elif model:
        head += f"<p>Applies to: {_e(', '.join(d.get('models', [])))}</p>"
    if d.get("buttons"):
        head += f"<p><b>Panel:</b> {_e(', '.join(d['buttons']))}</p>"
    procs = "".join(f"<li><b>{PROCEDURE_LABELS[k]}:</b> {_e(v)}</li>" for k, v in d.get("procedures", {}).items())
    body = f"<h3>On the printer</h3><ul>{procs}</ul>" if procs else ""
    body += _table(d.get("lights", []), "Lights")
    body += _table(d.get("lcd_codes", []), "Screen codes")
    if d.get("notes"):
        body += "<h3>Notes</h3><ul>" + "".join(f"<li>{_e(n)}</li>" for n in d["notes"]) + "</ul>"
    return head + body + _sources(d.get("sources", []))


def guide_html(g: dict, p: Profile) -> str:
    out = f"<h2>{_e(g['title'])}</h2>"
    if g.get("symptoms"):
        out += f"<p><small>When: {_e(', '.join(g['symptoms']))}</small></p>"
    out += "<ol>" + "".join(f"<li><b>{_e(s['title'])}.</b> {_e(p.fill(s['text']))}</li>" for s in g["steps"]) + "</ol>"
    if g.get("warnings"):
        out += "<p><b>Warnings</b></p><ul>" + "".join(f"<li>{_e(w)}</li>" for w in g["warnings"]) + "</ul>"
    if g.get("tips"):
        out += "<p><b>Tips</b></p><ul>" + "".join(f"<li>{_e(t)}</li>" for t in g["tips"]) + "</ul>"
    if p.key != "generic" and any("{" + k + "}" in s["text"] for s in g["steps"] for k in PROCEDURE_LABELS):
        out += f"<p><small>Button steps shown for: {_e(p.name)}</small></p>"
    return out + _sources(g.get("sources", []))


def profile_text(p: Profile) -> str:
    d = p.data
    lines = [p.name, "=" * len(p.name)]
    for k, v in d.get("procedures", {}).items():
        lines.append(f"{PROCEDURE_LABELS[k]}: {v}")
    for title, key in (("Lights", "lights"), ("Screen codes", "lcd_codes")):
        if d.get(key):
            lines += ["", title + ":"]
            lines += [f"  {r['pattern']}: {r['meaning']}" + (f" -> {r['action']}" if r["action"] else "") for r in d[key]]
    for n in d.get("notes", []):
        lines.append(f"Note: {n}")
    return "\n".join(lines)


def guide_text(g: dict, p: Profile) -> str:
    lines = [g["title"], "=" * len(g["title"])]
    lines += [f"{i + 1}. {s['title']}: {p.fill(s['text'])}" for i, s in enumerate(g["steps"])]
    lines += [f"! {w}" for w in g.get("warnings", [])]
    lines += [f"Tip: {t}" for t in g.get("tips", [])]
    return "\n".join(lines)
