# Vendored upstream data

| File | Origin | License | Used for |
|---|---|---|---|
| `devices.xml` | [CiRIP/ez-reset](https://github.com/CiRIP/ez-reset) `src/ez_reset/devices.xml` | AGPL-3.0-or-later | Main model database: keys, waste counters, reset sequences, counters, fatal error tables |
| `reinkpy_epson.toml` | [atufi/reinkpy](https://codeberg.org/atufi/reinkpy) `reinkpy/epson.toml` | AGPL-3.0-or-later | Cross-check of read/write keys |
| `padzero_models.json` | [Damnitbran/padzero](https://github.com/Damnitbran/padzero) | AGPL-3.0-or-later | Reference (verified-on-hardware notes) |
| `epc_printer_config.py` | [Ircama/epson_print_conf](https://github.com/Ircama/epson_print_conf) `EpsonPrinter.PRINTER_CONFIG` | EUPL-1.2 (compatible with AGPL-3.0) | Cross-check, community-verified flags |

Regenerate `egm/data/models.json` with `python tools/build_models.py` after updating any of these.
