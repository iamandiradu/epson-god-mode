#!/usr/bin/env python3
"""Source of truth for egm/data/troubleshooting.json.

Two kinds of content:

* SERIES -- per model series, taken from Epson's official user guides
  (files.support.epson.com / download4.epson.biz / Epson FAQ pages), paraphrased:
  control panel, light patterns or LCD codes, and the button/menu procedures
  for nozzle check, head cleaning and power cleaning.  Every entry lists its
  sources.  Models are listed explicitly; anything else falls back to the
  generic guidance for its panel type.
* GUIDES -- symptom-driven troubleshooting that applies to (almost) every
  ink tank model, written for this project: escalation for clogs, cap soak,
  single-colour purge, air in the tubes, waste pads, app-specific errors...
  Steps may contain tokens like ``{nozzle_check}`` that the app replaces with
  the selected series' procedure.

Run:  python tools/build_troubleshooting.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "egm" / "data" / "troubleshooting.json"

EPSON_UG = "https://files.support.epson.com/docid/"

# --------------------------------------------------------------------------- #
#  Shared light tables (several series share the exact same patterns)
# --------------------------------------------------------------------------- #
LIGHTS_L3110 = [
    ("Power on", "The printer is on.", ""),
    ("Power flashing", "Busy (printing, cleaning, charging).", "Wait until it stops before switching off."),
    ("Ink on", "Initial ink charging may not have finished.", "Follow the Start Here sheet."),
    ("Paper on", "No paper, or several sheets fed at once.", "Load paper, then press the B&W or Color copy button."),
    ("Paper flashing", "Paper jam.", "Remove the paper, then press a copy button."),
    ("Power + Paper flashing together", "Main waste ink pad near or at end of life (waste counter).",
     "Service the pads / fit an external waste tank, then reset the counter. A copy button lets you keep printing for now."),
    ("Power + Paper flashing alternately", "Borderless waste ink pad near or at end of life.",
     "As above; printing with borders still works, borderless stays disabled until reset."),
    ("All lights flashing", "Paper or packing material stuck inside, or printer error.",
     "Open the front cover, remove it, switch off and on. If it persists, read the last fatal error in Counters & errors."),
    ("Power off, Ink + Paper on", "Firmware update failed.", "Retry the update (over USB)."),
    ("Power on/flashing, Ink + Paper on", "The printer was not switched off properly.",
     "Press a copy button, run a nozzle check, cancel queued jobs. Always switch off with the power button."),
]
WIFI_ROWS = [
    ("Wi-Fi + Wi-Fi Direct flashing", "Wi-Fi connection error.", "Press the Wi-Fi button to clear it and try again."),
    ("Ink + Paper + Wi-Fi + Wi-Fi Direct on", "Firmware update failed.", "Connect by USB and retry the update."),
]
LIGHTS_L3210 = [
    ("Power on", "The printer is on.", ""),
    ("Power flashing", "Busy.", "Wait until it stops before switching off."),
    ("Ink on", "Initial ink charging may not have finished.", "Follow the Start Here sheet."),
    ("Paper on", "No paper, or several sheets fed at once.", "Load paper, then press the B&W or Color copy button."),
    ("Paper flashing", "Paper jam.", "Remove the paper, then press a copy button."),
    ("Ink + Paper flashing together", "Main waste ink pad near or at end of life.",
     "Service the pads / external tank, then reset the counter. A copy button lets you continue for now."),
    ("Ink + Paper flashing alternately", "Borderless waste ink pad near or at end of life.",
     "As above; borderless printing stays disabled until reset."),
    ("All lights flashing", "Printer error, often paper or packing material inside.",
     "Open the front cover, remove it, switch off and on."),
    ("Ink + Paper on (power on/flashing)", "Not switched off properly.",
     "Press a copy button, nozzle check, cancel queued jobs; switch off with the power button."),
    ("Ink + Paper on (power off)", "Firmware update failed.", "Connect by USB and retry the update."),
]
LIGHTS_L1210 = [
    ("Power on", "The printer is on.", ""),
    ("Power flashing", "Busy.", "Wait until it stops before switching off."),
    ("Ink on", "Initial ink charging may not have finished.", "Follow the Start Here sheet."),
    ("Paper on", "No paper, or several sheets fed at once.", "Load paper, press Stop."),
    ("Paper flashing", "Paper jam.",
     "Remove the paper and press Stop. Still flashing: switch off/on; then load A4/Letter in the rear feed and press Stop."),
    ("Ink + Paper flashing together", "Main waste ink pad near or at end of life.",
     "Service the pads / external tank, then reset the counter. Stop lets you continue for now."),
    ("Ink + Paper flashing alternately", "Borderless waste ink pad near or at end of life.", "As above."),
    ("All lights flashing", "Paper or packing material inside.", "Open the front cover, remove it, switch off and on."),
    ("Power on/flashing, Ink + Paper on", "Not switched off properly.",
     "Press Stop, nozzle check, cancel queued jobs; switch off with the power button."),
    ("Power off, Ink + Paper on", "Firmware update failed.", "Retry the update."),
]
LCD_CODES = [
    ("E-01", "Printer error.", "Switch off and on. Check for a paper jam. Read the last fatal error in Counters & errors."),
    ("E-02", "Scanner error.", "Switch off and on."),
    ("E-11", "Main waste ink pad at end of life; printing stops (scanning still works).",
     "Service the pads / external tank, then reset the counter."),
    ("E-12", "Borderless waste ink pad at end of life.", "As above; printing with borders still works."),
    ("W-01", "Paper jam.", "Remove the paper, press the button shown on the screen; switch off/on if it persists."),
    ("W-11", "Main waste ink pad nearing end of life.", "Plan pad service; press OK/Start to keep printing."),
    ("W-14", "Borderless waste ink pad nearing end of life.", "As above."),
    ("I-22 / I-23 / I-31", "Wireless setup prompts (WPS button, PIN, configure from a computer).", "Follow the screen."),
    ("I-41", "Paper Setup Auto Display is off (needed for AirPrint).", "Turn it on in the settings."),
    ("Recovery Mode", "Firmware update failed.", "Connect by USB and retry the update."),
]


def lights(rows):
    return [{"pattern": p, "meaning": m, "action": a} for p, m, a in rows]


def ug(path):
    return EPSON_UG + path


# --------------------------------------------------------------------------- #
#  Procedures (what to press on the printer)
# --------------------------------------------------------------------------- #
P_NOZZLE_STOP = "Switch the printer off, load plain paper, hold Stop and press Power; release both when it powers on."
P_CLEAN_STOP5 = "Load plain paper, hold Stop for 5 seconds; the power light flashes during cleaning and stays on when done."
P_CLEAN_STOP3 = "Load plain paper, hold Stop for 3 seconds; the power light flashes during cleaning and stays on when done."
P_POWER_UTILITY = ("From the computer only: Epson printer driver > Maintenance > Power Cleaning (Mac: Printer Utility). "
                   "Every tank at least one-third full; wait 12 hours before repeating.")
P_POWER_DRIVER = ("From the Epson driver: Maintenance > Power Cleaning (some models also offer it on the screen). "
                  "Every tank at least one-third full; wait 12 hours before repeating.")
P_LCD_NOZZLE = "Home > Maintenance > Nozzle Check > OK, then Start."
P_LCD_CLEAN = "Home > Maintenance > Head Cleaning > OK, then Start. Never switch off or open the cover during the cycle."
P_LCD_POWER = "Home > Maintenance > Power Cleaning > OK and follow the screen. Every tank at least one-third full."

P_FLUSH = ("Computer only: Epson driver > Maintenance > Ink Tube Flushing / Power Ink Flushing. "
           "Refill the tanks first; switch off and wait 12 hours afterwards.")

SERIES = {
    "L310": {
        "name": "L310 / L312 (printer, 3 lights)",
        "models": "L310 L312",
        "panel": "buttons",
        "buttons": ["Power", "Stop"],
        "lights": lights([
            ("Power on", "The printer is on.", ""),
            ("Power flashing", "Busy. After an ink fill it flashes for about 20 minutes.", "Do not interrupt it."),
            ("Paper on", "No paper or multiple sheets fed.", "Load paper, press Stop."),
            ("Paper flashing", "Paper jam.", "Remove it, press Stop."),
            ("Power + Ink on", "Initial ink charging may be incomplete.", "Follow the Start Here poster."),
            ("Paper + Ink flashing", "Waste ink pads need service.",
             "Service the pads / fit an external waste tank, then reset the counter."),
            ("Power + Paper + Ink flashing", "Paper or packing material inside.", "Open the cover, remove it, switch off and on."),
            ("Paper + Ink on", "Firmware update failed.", "Connect by USB and retry."),
        ]),
        "procedures": {"nozzle_check": P_NOZZLE_STOP, "head_cleaning": P_CLEAN_STOP3, "power_cleaning": P_FLUSH},
        "notes": ["Older generation: 'Ink Tube Flushing' instead of Power Cleaning.",
                  "Official escalation: up to 3 cleanings, switch off 12 hours, check again, then flush the tubes."],
        "sources": [ug("cpd4/cpd42407/source/printers/source/troubleshooting/reference/l310/problem_light_status_l310.html"),
                    ug("cpd4/cpd42407/source/printers/source/ink_functions/tasks/cleaning_head_buttons_spc.html"),
                    ug("cpd4/cpd42407/source/printers/source/ink_functions/concepts/ink_tube_flushing.html")],
    },
    "L110": {
        "name": "L110 / L210 / L300 / L350 / L355 (first generation)",
        "models": "L110 L111 L210 L211 L300 L301 L303 L308 L350 L351 L353 L355 L358",
        "panel": "buttons",
        "buttons": ["Power", "Stop"],
        "lights": lights([
            ("Power on", "The printer is on.", ""),
            ("Power flashing", "Busy. After an ink fill it flashes for about 20 minutes.", "Do not interrupt it."),
            ("Power flashing + Paper flashing", "Paper jam.", "Remove it, press Stop."),
            ("Power flashing + Paper on", "No paper or multiple sheets fed.", "Load paper, press Stop."),
            ("Ink flashing (power on or flashing)", "Ink probably low; levels need resetting soon.",
             "Check the tanks by eye and get ink; printing continues."),
            ("Ink on (power on or flashing)", "Ink reached the lower line.",
             "Refill and reset the ink levels; running below the line can damage the printer."),
            ("Ink + Paper flashing (power on or flashing)", "Waste ink pads near end of life.",
             "Service the pads / external tank, then reset the counter."),
            ("Power + Ink + Paper flashing", "Fatal error.", "Switch off and on; check for a jam."),
            ("Ink + Paper on", "Firmware update failed.", "Connect by USB and retry."),
        ]),
        "procedures": {"nozzle_check": P_NOZZLE_STOP, "head_cleaning": P_CLEAN_STOP3, "power_cleaning": P_FLUSH},
        "notes": ["This generation tracks ink levels by estimate: after refilling, reset the ink level as the driver asks.",
                  "The paper and ink lights share one spot on the panel."],
        "sources": [ug("cpd4/cpd40789/source/troubleshooting/reference/l210_l350/problem_light_status_l110_l355.html"),
                    ug("cpd4/cpd40789/source/printers/source/ink_functions/tasks/cleaning_head_buttons_spc.html")],
    },
    "L365": {
        "name": "L220 / L360 / L365 (all-in-one, 3 lights)",
        "models": "L220 L222 L360 L362 L364 L365 L366",
        "panel": "buttons",
        "buttons": ["Power", "B&W copy", "Color copy", "Stop", "Wi-Fi (L365/L366)"],
        "lights": lights([
            ("Power on", "The printer is on.", ""),
            ("Power flashing", "Busy.", "Wait until it stops before switching off."),
            ("Paper flashing", "Paper jam.", "Remove it, press a copy button."),
            ("Paper on", "No paper or multiple sheets fed.", "Load paper, press a copy button."),
            ("Power + Ink on", "Initial ink charging may be incomplete.", "Follow the Start Here poster."),
            ("Ink + Paper flashing", "Waste ink pads need service.", "Service the pads / external tank, then reset."),
            ("Ink + Paper on", "Firmware update failed.", "Connect by USB and retry."),
            ("Power + Ink + Paper flashing", "Paper or packing material inside.", "Open the scanner unit, remove it, switch off and on."),
        ]),
        "procedures": {"nozzle_check": P_NOZZLE_STOP, "head_cleaning": P_CLEAN_STOP3, "power_cleaning": P_FLUSH},
        "notes": ["Button procedures as in the L380 guide, which shares this control panel."],
        "sources": [ug("cpd4/cpd42421/source/troubleshooting/reference/l365/problem_light_status_l365.html"),
                    ug("cpd5/cpd52154/source/printers/source/ink_functions/tasks/cleaning_head_buttons_spc.html")],
    },
    "L3110": {
        "name": "L3110 / L3111 series (USB, buttons)",
        "models": "L3100 L3101 L3110 L3111 L3115 L3116 L3117 L3118 L3119",
        "panel": "buttons",
        "buttons": ["Power", "B&W copy", "Color copy", "Stop"],
        "lights": lights(LIGHTS_L3110),
        "procedures": {"nozzle_check": P_NOZZLE_STOP, "head_cleaning": P_CLEAN_STOP5,
                       "power_cleaning": P_POWER_UTILITY},
        "notes": ["Waste pad warning = Power + Paper lights flashing (not Ink + Paper like the newer L32xx).",
                  "No Power Cleaning on the panel; run it from the Epson driver."],
        "sources": [ug("cpd5/cpd55457/source/troubleshooting/reference/l3110/problem_light_status_l3110.html"),
                    ug("cpd5/cpd55457/source/printers/source/ink_functions/tasks/checking_nozzles_buttons_spc.html"),
                    ug("cpd5/cpd55457/source/printers/source/ink_functions/tasks/power_cleaning_utility.html")],
    },
    "L3150": {
        "name": "L3150 / L3156 series (Wi-Fi, buttons)",
        "models": "L3150 L3151 L3152 L3153 L3156 L3158",
        "panel": "buttons",
        "buttons": ["Power", "Wi-Fi", "Network status", "B&W copy", "Color copy", "Stop"],
        "lights": lights(LIGHTS_L3110[:-2] + WIFI_ROWS + [LIGHTS_L3110[-1]]),
        "procedures": {"nozzle_check": P_NOZZLE_STOP, "head_cleaning": P_CLEAN_STOP5,
                       "power_cleaning": P_POWER_UTILITY},
        "notes": ["Many units refuse EEPROM access over Wi-Fi; connect by USB for counter resets."],
        "sources": [ug("cpd5/cpd55466/source/troubleshooting/reference/l3150/problem_light_status_l3150.html"),
                    ug("cpd5/cpd55466/source/printers/source/ink_functions/tasks/cleaning_head_buttons_spc.html")],
    },
    "L3210": {
        "name": "L3210 / L3211 / L3215 / L3216 series (USB, buttons)",
        "models": "L3200 L3201 L3203 L3205 L3206 L3210 L3211 L3215 L3216 L3217 L3218 L3219",
        "panel": "buttons",
        "buttons": ["Power", "B&W copy", "Color copy", "Stop"],
        "lights": lights(LIGHTS_L3210),
        "procedures": {"nozzle_check": P_NOZZLE_STOP, "head_cleaning": P_CLEAN_STOP5,
                       "power_cleaning": P_POWER_UTILITY},
        "notes": ["Waste pad warning = Ink + Paper lights flashing.",
                  "Recent firmware may lock EEPROM writes; if the reset is refused, try the app's temporary reset (rw)."],
        "sources": [ug("cpd6/cpd60181/source/troubleshooting/reference/l3210/problem_light_status_l3210.html"),
                    ug("cpd6/cpd60181/source/printers/source/ink_functions/tasks/cleaning_head_buttons_spc.html"),
                    ug("cpd6/cpd60181/source/printers/source/ink_functions/concepts/power_cleaning.html")],
    },
    "L3250": {
        "name": "L3250 / L3251 / L3252 / L3256 series (Wi-Fi, buttons)",
        "models": "L3250 L3251 L3252 L3253 L3255 L3256 L3257 L3258 L3259",
        "panel": "buttons",
        "buttons": ["Power", "Wi-Fi", "Network status", "B&W copy", "Color copy", "Stop"],
        "lights": lights([r for r in LIGHTS_L3210 if not r[0].startswith("Ink + Paper on (power off)")] + WIFI_ROWS),
        "procedures": {"nozzle_check": P_NOZZLE_STOP, "head_cleaning": P_CLEAN_STOP5,
                       "power_cleaning": P_POWER_UTILITY},
        "notes": ["EEPROM access over Wi-Fi is blocked on current firmware: use USB.",
                  "The waste reset on this generation needs an extra flag step; the app does it automatically."],
        "sources": [ug("cpd6/cpd60185/source/troubleshooting/reference/l3250/problem_light_status_l3250.html"),
                    ug("cpd6/cpd60185/source/product_info/reference/l3250/control_panel_buttons_lights_l3250.html")],
    },
    "L3160": {
        "name": "L3160 / ET-2720 series (small colour screen)",
        "models": "L3160 L3161 L3163 L3165 L3166 L3168 ET-2720 ET-2721 ET-2723 ET-2725 ET-2726",
        "panel": "lcd",
        "buttons": ["Power", "Home", "arrows", "OK", "Start", "Stop", "Back"],
        "lcd_codes": lights(LCD_CODES),
        "procedures": {"nozzle_check": P_LCD_NOZZLE, "head_cleaning": P_LCD_CLEAN,
                       "power_cleaning": P_POWER_DRIVER},
        "notes": ["After a head cleaning the printer offers a nozzle check and asks whether to clean again: "
                  "answer No if most lines are missing and run a Power Cleaning instead."],
        "sources": [ug("cpd6/cpd60271/source/printers/source/ink_functions/tasks/et2720_l3160/cleaning_head_lcd_et2720_l3160.html")],
    },
    "L3260": {
        "name": "L3260 / ET-2800 series (small colour screen)",
        "models": "L3260 L3261 L3263 L3265 L3266 L3267 L3268 ET-2800 ET-2801 ET-2803 ET-2805",
        "panel": "lcd",
        "buttons": ["Power", "Home", "arrows", "OK", "Start", "Stop", "Back"],
        "lcd_codes": lights(LCD_CODES),
        "procedures": {"nozzle_check": P_LCD_NOZZLE, "head_cleaning": P_LCD_CLEAN, "power_cleaning": P_LCD_POWER},
        "notes": ["Power Cleaning is available on the screen (Maintenance menu).",
                  "EEPROM access over the network is blocked on current firmware; use USB."],
        "sources": [ug("cpd6/cpd60271/source/printers/source/ink_functions/tasks/et2800_l3260/power_cleaning_lcd_et2800_l3260.html"),
                    ug("cpd6/cpd60271/source/printers/source/ink_functions/tasks/et2720_l3160/cleaning_head_lcd_et2720_l3160.html")],
    },
    "L1210": {
        "name": "L1110 / L1210 / L1250 printers (no scanner, buttons)",
        "models": "L1110 L1118 L1119 L1210 L1216 L1218 L1219 L1250 L1256 L1258 L1259",
        "panel": "buttons",
        "buttons": ["Power", "Stop", "Wi-Fi (L1250)"],
        "lights": lights(LIGHTS_L1210),
        "procedures": {"nozzle_check": P_NOZZLE_STOP, "head_cleaning": P_CLEAN_STOP5,
                       "power_cleaning": P_POWER_UTILITY},
        "notes": ["The single Stop button clears errors, prints the nozzle check (held at power-on) and cleans (held 5 s)."],
        "sources": [ug("cpd5/cpd59907/source/printers/source/ink_functions/tasks/cleaning_head_buttons_spc.html"),
                    ug("cpd5/cpd59907/source/printers/source/ink_functions/concepts/power_cleaning.html"),
                    "https://epson.com.jm/faq/SPT_C11CJ70301~faq-0000800-l1210"],
    },
    "L120": {
        "name": "L120 / L121 (printer, power + error lights)",
        "models": "L120 L121",
        "panel": "buttons",
        "buttons": ["Power", "Cancel (stop icon)"],
        "lights": lights([
            ("Power on", "The printer is on.", ""),
            ("Power flashing", "Busy. After an ink fill it flashes for about 20 minutes.", "Do not interrupt it."),
            ("Power + Error flashing", "Paper jam or printer error.",
             "Remove the paper, press Cancel; if it keeps flashing switch off, check for foreign objects, switch on."),
            ("Power + Error flashing simultaneously (persistent)", "Waste ink pad near or at end of life.",
             "Service the pads / external tank, then reset the counter."),
            ("Power flashing, Error on", "No paper or multiple sheets fed.", "Load paper, press Cancel."),
            ("Power on, Error on", "Initial ink charging may be incomplete.", "Switch off and follow the Start Here sheet."),
            ("Power off, Error on", "Firmware update failed.", "Connect by USB and retry."),
        ]),
        "procedures": {"nozzle_check": "Switch off, load paper, hold Cancel and press Power; release both when it powers on.",
                       "head_cleaning": "Load paper, hold Cancel for 3 seconds; power light flashes until done.",
                       "power_cleaning": "Computer only: driver > Maintenance > Power Ink Flushing (refill tanks first)."},
        "notes": ["On these two-light models a jam and a waste pad warning both flash Power + Error; "
                  "check the waste counter in this app to tell them apart."],
        "sources": [ug("cpd4/cpd40202/source/printers/source/troubleshooting/reference/l120/problem_light_status_l120.html"),
                    ug("cpd4/cpd40202/source/printers/source/ink_functions/tasks/cleaning_head_buttons_spc.html")],
    },
    "L380": {
        "name": "L380 / L382 / L385 / L395 (buttons)",
        "models": "L380 L382 L385 L386 L395 L396",
        "panel": "buttons",
        "buttons": ["Power", "B&W copy", "Color copy", "Stop", "Wi-Fi (L386/L396)"],
        "lights": lights([
            ("Power on", "The printer is on.", ""),
            ("Power flashing", "Busy.", "Wait until it stops before switching off."),
            ("Paper flashing", "Paper jam.", "Remove it, press a copy button."),
            ("Paper on", "No paper or multiple sheets fed.", "Load paper, press a copy button."),
            ("Power + Ink on", "Initial ink charging may be incomplete.", "Follow the Start Here poster."),
            ("Ink + Paper flashing", "Waste ink pads need service.", "Service the pads / external tank, then reset."),
            ("Ink + Paper on", "Firmware update failed.", "Connect by USB and retry."),
            ("All lights flashing", "Paper or packing material inside.", "Open the scanner unit, remove it, switch off and on."),
        ]),
        "procedures": {"nozzle_check": P_NOZZLE_STOP, "head_cleaning": P_CLEAN_STOP3,
                       "power_cleaning": "Computer only: driver > Maintenance > Power Ink Flushing (refill tanks first; wait 12 h after)."},
        "notes": ["Older generation: 'Power Ink Flushing' instead of Power Cleaning."],
        "sources": ["https://epson.com.jm/faq/SPT_C11CF43301~faq-0000800-l380",
                    ug("cpd5/cpd52154/source/printers/source/ink_functions/tasks/cleaning_head_buttons_spc.html"),
                    ug("cpd5/cpd52154/source/printers/source/ink_functions/concepts/ink_tube_flushing.html")],
    },
    "L4150": {
        "name": "L4150 / ET-2700 series (Wi-Fi, buttons)",
        "models": "L4150 L4152 L4154 L4156 L4158 ET-2700 ET-2701 ET-2703 ET-2705",
        "panel": "buttons",
        "buttons": ["Power", "Wi-Fi", "Network status", "B&W copy", "Color copy", "Stop"],
        "lights": lights([
            ("Power on", "The printer is on.", ""),
            ("Power flashing", "Busy.", "Wait until it stops before switching off."),
            ("Power + Ink on", "Initial ink charging may be incomplete.", "Follow the Start Here sheet."),
            ("Paper on", "No paper or multiple sheets fed.", "Load paper, press a copy button."),
            ("Paper flashing", "Paper jam.", "Remove it, press a copy button."),
            ("Power + Paper flashing", "Waste ink pad near or at end of life.",
             "Service the pads / external tank, then reset. A copy button lets you continue for now."),
            ("All lights flashing", "Paper or packing material inside.", "Open the scanner unit, remove it, switch off and on."),
        ] + WIFI_ROWS + [("Ink + Paper on", "Not switched off properly.",
                          "Press a copy button, nozzle check, cancel queued jobs; switch off with the power button.")]),
        "procedures": {"nozzle_check": P_NOZZLE_STOP, "head_cleaning": P_CLEAN_STOP5,
                       "power_cleaning": P_POWER_UTILITY},
        "notes": [],
        "sources": [ug("cpd5/cpd53991/source/troubleshooting/reference/et2700_2750/problem_light_status_et2700.html"),
                    ug("cpd5/cpd54034/helpcontents.html")],
    },
    "L4160": {
        "name": "L4160 / ET-2750 series (colour screen)",
        "models": "L4160 L4162 L4164 L4166 L4168 ET-2750 ET-2751 ET-2756",
        "panel": "lcd",
        "buttons": ["Power", "Home", "arrows", "OK", "Start", "Stop", "Back", "Help"],
        "lcd_codes": lights(LCD_CODES),
        "procedures": {"nozzle_check": P_LCD_NOZZLE, "head_cleaning": P_LCD_CLEAN, "power_cleaning": P_POWER_DRIVER},
        "notes": [],
        "sources": [ug("cpd5/cpd59900/source/printers/source/ink_functions/tasks/et2850_l4260/cleaning_head_lcd_et2850.html")],
    },
    "L4260": {
        "name": "L4260 / ET-2850 series (colour screen)",
        "models": "L4260 L4261 L4263 L4265 L4266 L4267 L4268 L4269 ET-2850 ET-2851 ET-2853 ET-2855",
        "panel": "lcd",
        "buttons": ["Power", "Home", "arrows", "OK", "Start", "Stop", "Back"],
        "lcd_codes": lights(LCD_CODES),
        "procedures": {"nozzle_check": P_LCD_NOZZLE, "head_cleaning": P_LCD_CLEAN, "power_cleaning": P_LCD_POWER},
        "notes": ["EEPROM access over the network is blocked on current firmware; use USB."],
        "sources": [ug("cpd5/cpd59900/source/troubleshooting/reference/et2850_et2850u_l4260/problem_message_status_et2850.html"),
                    ug("cpd5/cpd59900/source/printers/source/ink_functions/concepts/power_cleaning_tanks.html")],
    },
    "L5190": {
        "name": "L5190 / ET-4700 series (screen, ADF, fax on some)",
        "models": "L5190 L5196 L5198 ET-4700",
        "panel": "lcd",
        "buttons": ["Power", "Home", "arrows", "OK", "Start", "Stop", "Back", "Help"],
        "lcd_codes": lights(LCD_CODES),
        "procedures": {"nozzle_check": P_LCD_NOZZLE, "head_cleaning": P_LCD_CLEAN,
                       "power_cleaning": ("With the printer off, hold Power + Help together until the Power Cleaning "
                                          "screen appears, then follow it. Every tank at least one-third full.")},
        "notes": ["Power Cleaning is started with a Power + Help button combination, not from the menu."],
        "sources": [ug("cpd5/cpd56096/source/troubleshooting/reference/et4700_l5190/problem_message_status_et4700_l5190.html"),
                    ug("cpd5/cpd56096/source/printers/source/ink_functions/tasks/et4700_l5190/power_cleaning_lcd_et4700_l5190.html")],
    },
    "L5290": {
        "name": "L5290 / ET-4800 series (screen, ADF)",
        "models": "L5290 L5296 L5298 ET-4800 ET-4810",
        "panel": "lcd",
        "buttons": ["Power", "Home", "arrows", "OK", "Start", "Stop", "Back"],
        "lcd_codes": lights(LCD_CODES),
        "procedures": {"nozzle_check": P_LCD_NOZZLE, "head_cleaning": P_LCD_CLEAN, "power_cleaning": P_LCD_POWER},
        "notes": ["ET-4800 waste reset is verified on hardware by the padzero project."],
        "sources": [ug("cpd6/cpd60263/source/printers/source/ink_functions/tasks/et4800_l5290/power_cleaning_lcd_et4800_l5290.html"),
                    ug("cpd6/cpd60263/source/troubleshooting/reference/et4700_l5190/problem_message_status_et4700_l5190.html")],
    },
    "L6190": {
        "name": "L6190 / ET-4750 series (screen, duplex, ADF, fax)",
        "models": "L6190 L6191 L6196 L6198 ET-4750",
        "panel": "lcd",
        "buttons": ["Power", "Home", "arrows", "OK", "Start", "Stop", "Back", "Help"],
        "lcd_codes": lights(LCD_CODES),
        "procedures": {"nozzle_check": P_LCD_NOZZLE, "head_cleaning": P_LCD_CLEAN, "power_cleaning": P_POWER_DRIVER},
        "notes": ["The screen reports borderless pad warnings as text messages; the main pad uses the usual E-/W- codes."],
        "sources": [ug("cpd5/cpd56457/source/troubleshooting/reference/et4750/problem_message_status_et4750.html")],
    },
    "ET4850": {
        "name": "ET-4850 / L6270 series (screen, duplex, ADF, fax)",
        "models": "ET-4850 L6270 L6276 L6278",
        "panel": "lcd",
        "buttons": ["Power", "Home", "arrows", "OK", "Start", "Stop", "Back"],
        "lcd_codes": lights(LCD_CODES),
        "procedures": {"nozzle_check": P_LCD_NOZZLE, "head_cleaning": P_LCD_CLEAN, "power_cleaning": P_LCD_POWER},
        "notes": ["Network EEPROM access is blocked on recent firmware; use USB."],
        "sources": [ug("cpd6/cpd60205/source/troubleshooting/reference/et4850/problem_message_status_et4850.html")],
    },
    "L805": {
        "name": "L805 / L810 (6-colour photo, CD/DVD printing)",
        "models": "L805 L810",
        "panel": "buttons",
        "buttons": ["Power", "Wi-Fi", "Network status", "Ink", "Paper/Cancel"],
        "lights": lights([
            ("Power on", "The printer is on.", ""),
            ("Power flashing", "Busy.", "Wait until it stops before switching off."),
            ("Paper/Cancel on", "No paper or disc, or multiple sheets fed.", "Load paper/disc, press Paper/Cancel."),
            ("Paper/Cancel flashing slowly", "Paper jam.", "Remove it, press Paper/Cancel."),
            ("Paper/Cancel flashing quickly", "Paper too small to eject.", "Remove it by hand or load a larger size."),
            ("Ink on", "Initial ink charging may be incomplete.", "Follow the Start Here poster."),
            ("Paper/Cancel + Ink flashing alternately", "Waste ink pads need service.",
             "Service the pads / external tank, then reset the counter."),
            ("Ink quick + Paper/Cancel slow flashing", "Output tray in the wrong position (paper vs disc).", "Set the tray correctly."),
            ("Ink + Paper/Cancel flashing slowly", "Printer cover open.", "Close the cover."),
            ("Network status flashing slowly", "Network error.", "Hold the network status button, then reconnect."),
            ("All lights flashing quickly", "Packing material inside.", "Remove it, switch off and on."),
            ("All lights on", "Firmware update failed.", "Connect by USB and retry."),
        ]),
        "procedures": {"nozzle_check": "Switch off, load paper, hold Paper/Cancel and press Power; release when it powers on.",
                       "head_cleaning": "Load paper (no CD tray inserted), hold the Ink button for 3 seconds.",
                       "power_cleaning": "Computer only: driver > Maintenance > Power Ink Flushing (refill first; wait 12 h)."},
        "notes": ["Six colours: purging a single colour with a printed page saves a lot of ink on this model."],
        "sources": ["https://epson.com.jm/faq/SPT_C11CE86301~faq-0000800-l805",
                    ug("cpd5/cpd50133/source/printers/source/ink_functions/tasks/cleaning_head_buttons_spc.html")],
    },
    "L1800": {
        "name": "L1800 / L1300 (A3)",
        "models": "L1800 L1300",
        "panel": "buttons",
        "buttons": ["Power", "Paper", "Ink", "Cancel"],
        "lights": lights([
            ("Power flashing", "Busy. After an ink fill it flashes for about 20 minutes.", "Do not interrupt it."),
            ("Paper flashing", "Paper jam (L1300: cover may be open).", "Remove it, press Cancel."),
            ("Paper on", "No paper or multiple sheets fed.", "Load paper, press Cancel."),
            ("Paper + Ink flashing alternately", "Waste ink pads near end of life.",
             "Service the pads / external tank, then reset. Cancel lets you continue for now."),
            ("Power on, Paper + Ink flashing slowly", "Unknown error.", "Switch off/on, check for a jam."),
            ("Ink on 3 s, then Power flashing", "Initial ink charging.", "Wait about 20 minutes."),
        ]),
        "procedures": {"nozzle_check": "Switch off, load paper, hold Paper and press Power; release when it powers on.",
                       "head_cleaning": "Load paper, hold the Ink button for 3 seconds.",
                       "power_cleaning": "Computer only: Power Ink Flushing in the driver (refill first; wait 12 h)."},
        "notes": [],
        "sources": [ug("cpd4/cpd40326.pdf")],
    },
    "L8050": {
        "name": "L8050 / L18050 / ET-18100 (photo, maintenance box)",
        "models": "L8050 L8058 L18050 L18058 ET-18100",
        "panel": "buttons",
        "buttons": ["Power", "Resume/Cancel", "Wi-Fi"],
        "lights": lights([
            ("Paper on", "No paper / tray not inserted correctly.", "Load paper or reseat the CD/ID tray, press the button."),
            ("Paper jam light", "Jam, or disc/ID card misplaced.", "Clear it, press the button."),
            ("Maintenance box flashing", "Maintenance box nearly full.", "Replace the maintenance box (user-replaceable)."),
            ("Maintenance box flashing alternately", "Cleaning impossible: box full, missing or end of life.",
             "Replace or reseat the maintenance box."),
            ("Ink pad lights flashing together", "Internal ink pad near or at end of life; cleaning stops.",
             "Service the pads, then reset the counter."),
            ("Borderless pad lights flashing alternately", "Borderless pad near or at end of life.", "As above."),
            ("Power flashing", "Not switched off properly; nozzles may have dried.", "Clear it, run a nozzle check."),
            ("Transport lock light", "Transportation lock engaged.", "Unlock it, press the button."),
            ("Output tray light", "Output tray not extended.", "Slide it out."),
            ("All lights on except power", "Recovery mode after a failed firmware update.", "Connect by USB and retry."),
            ("All lights flashing", "Printer error.", "Remove any paper inside, switch off and on."),
        ]),
        "procedures": {"nozzle_check": "Switch off, load A4 paper, hold the second (resume) button while switching on; release when Power flashes.",
                       "head_cleaning": "Hold the second (resume) button for 5 seconds until Power flashes.",
                       "power_cleaning": "Computer utility (driver > Maintenance > Power Cleaning)."},
        "notes": ["Most waste ink goes to a user-replaceable maintenance box: replace the box rather than resetting a counter.",
                  "Has a transportation lock: always lock it before moving the printer."],
        "sources": ["https://download4.epson.biz/sec_pubs/l8050_series/useg/en/GUID-8C9B57F8-F49E-492C-82B4-BF4E279F278A.htm",
                    "https://download4.epson.biz/sec_pubs/l8050_series/useg/en/GUID-784771D4-3E59-4F80-B94D-002B59E143D2.htm"],
    },
}

GENERIC = {
    "buttons": {
        "name": "Generic Epson ink tank printer with buttons and lights",
        "lights": lights([
            ("Power flashing", "Busy (printing, cleaning, charging).", "Wait until it stops."),
            ("Paper on / flashing", "No paper / paper jam.", "Load or remove paper, then press the copy or Stop button."),
            ("Two lights flashing together or alternately (ink + paper, or power + paper)",
             "Usually a waste ink pad warning (main or borderless).", "Check the waste counters in this app."),
            ("All lights flashing", "Printer error / something stuck inside.", "Open the covers, remove it, switch off and on."),
        ]),
        "procedures": {"nozzle_check": "Usually: switch off, hold Stop (or Cancel/Paper on older models) and press Power.",
                       "head_cleaning": "Usually: hold Stop (or the Ink button) for 3-5 seconds.",
                       "power_cleaning": "From the Epson driver's Maintenance tab (Power Cleaning or Power Ink Flushing)."},
        "notes": ["These patterns are the common Epson ones; check your model's user guide to be sure."],
    },
    "lcd": {
        "name": "Generic Epson ink tank printer with a screen",
        "lcd_codes": lights(LCD_CODES),
        "procedures": {"nozzle_check": P_LCD_NOZZLE, "head_cleaning": P_LCD_CLEAN, "power_cleaning": P_LCD_POWER},
        "notes": ["Epson uses the same E-/W-/I- code scheme across its ink tank models with screens."],
    },
}

# --------------------------------------------------------------------------- #
#  Guides
# --------------------------------------------------------------------------- #
def g(id_, title, category, symptoms, steps, warnings=(), tips=(), actions=(), sources=()):
    return {"id": id_, "title": title, "category": category, "symptoms": list(symptoms),
            "steps": [{"title": t, "text": x} for t, x in steps], "warnings": list(warnings),
            "tips": list(tips), "actions": list(actions), "sources": list(sources)}


GUIDES = [
    g("clogged-nozzles", "Lines missing in the nozzle check", "Print quality",
      ["gaps in the nozzle check", "one colour missing", "faint or streaky prints", "white lines"],
      [("Check the basics", "Ink tanks above the lower line, no air gaps in the tubes, plain paper loaded, no error lights."),
       ("Print a nozzle check", "{nozzle_check} In this app: Maintenance → Nozzle check pattern."),
       ("Only one colour affected?", "Print 2–3 solid pages of that colour first (see 'Purge a single colour'). "
                                      "It uses only that ink and nothing goes to the waste pads."),
       ("Clean once", "{head_cleaning} Then print another nozzle check."),
       ("Up to three cleanings", "If it improves, repeat up to three times in total, checking after each."),
       ("Rest", "Still gaps after three cleanings: switch off and wait at least 12 hours (or overnight). "
                "Soaking the cap meanwhile helps (see 'Soak the capping station')."),
       ("Power cleaning, once", "Only if most lines are still missing: {power_cleaning}"),
       ("Stop", "No improvement after a power cleaning and another 12-hour rest: the head may be damaged "
                "or a tube may be blocked; contact a service centre.")],
      warnings=["Every cleaning sends ink to the waste pads; back-to-back cleanings fill them fast.",
                "Power cleaning needs every tank at least one-third full, or it can damage the printer.",
                "Never switch off or open the cover during a cleaning."],
      tips=["A pattern that gets better each time is worth one more try; one that never changes needs rest, not cleaning."],
      actions=["nozzle", "clean_normal", "purge"],
      sources=[ug("cpd5/cpd55457/source/printers/source/ink_functions/tasks/power_cleaning_utility.html"),
               ug("cpd5/cpd59907/source/printers/source/ink_functions/concepts/power_cleaning.html")]),

    g("single-colour-purge", "Purge a single colour (save ink)", "Print quality",
      ["one colour clogged", "yellow missing", "cyan missing", "magenta missing", "black streaky"],
      [("Why", "Cleaning always pulls ink from every colour, because one cap covers the whole head. "
               "Printing a solid page fires only that colour's nozzles."),
       ("Make the page", "A page filled with pure colour: yellow RGB 255,255,0 · cyan 0,255,255 · "
                         "magenta 255,0,255 · black 0,0,0. Paint or Word is enough."),
       ("Print 2–3 pages", "Through the normal Epson driver, plain paper, standard quality, a few minutes apart."),
       ("Check", "Print a nozzle check. Better but gappy: repeat once. Unchanged: soak the cap, then try again.")],
      tips=["Works best when the colour is thin or broken, not completely missing.",
            "If a colour is missing entirely right after a refill or tube work, suspect air in the tube instead."],
      actions=["nozzle"]),

    g("soak-cap", "Soak the capping station (fluid under the head)", "Print quality",
      ["stubborn clog", "colour still missing after cleaning", "yellow cyan magenta black clogged",
       "nozzles not recovering", "printer unused for weeks"],
      [("Get the head off the cap", "Lift the scanner unit. Start a nozzle check or cleaning; as soon as the head "
                                    "moves left off its parking spot, pull the power cable from the wall. Don't use "
                                    "the power button: it parks the head first."),
       ("Find the cap and wiper", "On the right, where the head rests: a small rectangular rubber cap and a thin rubber "
                                  "blade next to it. Don't touch the clear encoder strip or the white ribbon cable."),
       ("Clean the cap rim and wiper", "Lint-free swab or cotton bud lightly dampened with distilled water. Dried ink on "
                                       "the rim stops the cap from sealing."),
       ("Fill the cap", "Distilled water or printhead cleaning fluid, a few drops, level with the rim, not overflowing."),
       ("Park the head on the wet cap", "Slide the head gently by hand back to the right until it sits in its parking "
                                        "position. Don't force it."),
       ("Let it soak", "Leave it unplugged at least 4 hours, ideally overnight. This uses no ink."),
       ("Plug in and check", "Switch on and print a nozzle check; judge the second or third pattern, not the first. "
                             "Better but gappy: purge that colour. Unchanged: soak once more before cleaning.")],
      warnings=["Never touch the nozzle plate under the head.",
                "No alcohol or household cleaners: they can harden the rubber.",
                "Don't slide the head sideways while it sits on the wet cap."],
      tips=["The same procedure works on all Epson ink tank printers whose head parks on the right."]),

    g("move-head", "Move the print head out of the way", "Maintenance",
      ["need to reach the cap", "head stuck in parking position", "clean under the head"],
      [("Why there's no button", "Epson printers only move the head themselves; there is no safe 'move head' command."),
       ("Unplug mid-movement", "Start a nozzle check or cleaning and pull the power cable as the head moves left. "
                               "Unplugged, the head slides by hand with light pressure."),
       ("Put it back", "Slide it to the right until it parks over the cap, or just switch on: the printer homes it.")],
      warnings=["Only unplug for maintenance; normally always switch off with the power button so the head gets capped."]),

    g("air-in-tubes", "A colour is completely missing after a refill", "Print quality",
      ["colour missing after refill", "air bubbles in tube", "ink not reaching head"],
      [("Look at the tank and tube", "Tank above the lower line? Visible air gaps in that colour's tube?"),
       ("Refill if low", "A tank below the lower line lets air into the system."),
       ("One ink charge", "Air in the tube needs an ink charge (or one power cleaning), not repeated normal cleanings. "
                          "Run it once, then rest and print a nozzle check.")],
      warnings=["An ink charge uses a lot of ink and fills the waste pads quickly."],
      actions=["ink_charge"]),

    g("waste-pads", "Waste ink pad full ('service required')", "Errors",
      ["two lights flashing", "E-11", "W-11", "service required", "ink pad end of life", "printer stopped printing"],
      [("Confirm it", "Open Waste ink pads in this app: a counter near or above 100% confirms it."),
       ("Deal with the ink", "The counter is an estimate, but the pads really do hold the ink. Replace or wash the pads, "
                             "or fit an external waste ink tank (a tube from the pad outlet to a bottle)."),
       ("Back up", "EEPROM → Full backup before changing anything."),
       ("Reset", "Waste ink pads → Reset counters. The app backs up the cells, writes and verifies them."),
       ("Power-cycle", "Switch the printer off and on to clear the error.")],
      warnings=["Resetting without servicing the pads can let ink leak out of the printer."],
      tips=["Models with a user-replaceable maintenance box (e.g. L8050/L18050): replace the box instead."],
      actions=["waste"]),

    g("not-switched-off", "Ink and paper lights on together after power-on", "Errors",
      ["ink and paper lights on", "power cut", "unplugged while on"],
      [("Clear it", "Press the copy (or Stop) button."),
       ("Check the head", "Print a nozzle check: the head may not have been capped and could have dried."),
       ("Prevent it", "Always switch off with the power button and wait for the light to go out before unplugging.")]),

    g("paper-jam", "Paper jam", "Errors",
      ["paper light flashing", "W-01", "paper stuck"],
      [("Cancel the job", "Cancel printing from the computer or with Stop."),
       ("Rear feed", "Gently pull jammed paper out of the rear feed slot."),
       ("Inside", "Open the front cover (or scanner unit) and remove paper and torn pieces. Don't touch the parts Epson marks."),
       ("Clear the error", "Close the cover and press the copy/Stop button.")]),

    g("banding", "White or dark lines across prints", "Print quality",
      ["banding", "horizontal lines", "streaks"],
      [("Nozzle check first", "Gaps in the pattern → follow 'Lines missing in the nozzle check'."),
       ("Paper settings", "Paper type in the driver must match the paper; load it printable side up."),
       ("Quality", "Turn off high-speed / bidirectional printing; use Standard or High quality."),
       ("Alignment", "Run Print Head Alignment from the driver's Maintenance tab."),
       ("Ink", "Refill low tanks.")],
      sources=[ug("cpd5/cpd55457/source/printers/source/troubleshooting/reference/problem_banding.html")]),

    g("ink-charge-noise", "Noise and flashing power light after filling ink", "Maintenance",
      ["noise after refill", "initial charging", "power light flashing for a long time"],
      [("It's normal", "Initial ink charging takes about 20 minutes with noise; the power light stops flashing when done."),
       ("Don't interrupt", "Switching off early can charge the head badly and waste ink later."),
       ("Stuck?", "No movement or noise for 20 minutes and still not finished: switch off and on and check again.")],
      sources=[ug("cpd5/cpd55457/source/printers/source/troubleshooting/reference/problem_noise_install_tanks.html")]),

    g("prevention", "Keep the head from clogging", "Maintenance",
      ["printer rarely used", "clogs after holidays"],
      [("Print something weekly", "A small colour page every week keeps every nozzle wet."),
       ("Keep tanks topped up", "Never run below the lower line."),
       ("Switch off properly", "Use the power button so the head gets capped; avoid power strips switched off while on."),
       ("Before a long break", "Print a nozzle check before leaving, and use the soak method if it comes back clogged.")]),

    g("app-stuck-print", "Printer stops mid-print with a high-pitched whine", "This app",
      ["stalled nozzle check", "whining", "half-printed page"],
      [("Release it", "Maintenance → Release stuck job sends a form feed that finishes the open page."),
       ("Or power-cycle", "Switch the printer off and on."),
       ("Why", "A job that never sends its end-of-page leaves the printer waiting for more data.")],
      actions=["release"]),

    g("app-access-denied", "USB 'access denied' (WinErr 5)", "This app",
      ["WinErr 5", "ACCESS_DENIED", "device I/O failed"],
      [("Wait", "Windows or Epson's status monitor is using the port, usually for a print job. The app reconnects by itself."),
       ("Check the queue", "Cancel stuck jobs in the Windows print queue."),
       ("Power", "Make sure the printer is on and not asleep.")]),

    g("app-cleaning-refused", "Cleaning refused (||:84:NA;)", "This app",
      ["cleaning refused", "84:NA", "cleaning disabled"],
      [("Read the reason", "The app checks the printer status first and names the blocker: error, not idle, cleaning "
                           "disabled for a colour, ink low."),
       ("Fallback", "When nothing blocks it, the app sends the Epson-driver cleaning directly instead and confirms it "
                    "by the waste counter rising."),
       ("Rate limits", "Some firmwares refuse strong/power cleaning shortly after another one; wait a while.")]),

    g("app-eeprom-refused", "Counter reset refused by the printer (:NA;)", "This app",
      ["EEPROM refused", "write refused", "NA"],
      [("Use USB", "Many recent firmwares block EEPROM access over the network."),
       ("Check the model", "A wrong model selection uses the wrong key; let the app auto-detect."),
       ("Temporary reset", "Waste ink pads → Temporary reset (rw) works on some locked firmwares; the effect may not be permanent.")]),
]


def main() -> None:
    series = {}
    for key, s in SERIES.items():
        s = dict(s)
        s["models"] = s["models"].split()
        series[key] = s
    doc = {"schema": 1, "series": series, "generic": GENERIC, "guides": GUIDES,
           "disclaimer": ("Light patterns and procedures are paraphrased from Epson's user guides for each series "
                          "(see sources). This project is not affiliated with Seiko Epson Corporation.")}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    n_models = sum(len(s["models"]) for s in series.values())
    print(f"series: {len(series)}  models mapped: {n_models}  guides: {len(GUIDES)}")


if __name__ == "__main__":
    main()
