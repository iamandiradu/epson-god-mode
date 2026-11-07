"""Core tests: protocol framing, model DB, and full flows against the simulator."""
import json

import pytest

from egm import printjobs as pj
from egm.modeldb import load
from egm.operations import PrinterSession, SafetyError
from egm.protocol import eeprom_read_frame, eeprom_write_frame, parse_status

FEATURED = ["L3110", "L3111", "L3150", "L3156", "L3160", "L3250", "L3251", "L3260", "L1110", "L1210",
            "L4150", "L4160", "L5190", "ET-2700", "ET-2710", "ET-2720", "ET-2750", "L3210", "L3211",
            "L3215", "L3216", "L3252", "L3256", "L1250", "L4260", "L5290", "L6190", "L805", "L1800",
            "L8050", "L18050", "L120", "L121", "L380", "L382", "ET-2800", "ET-2850", "ET-4800", "ET-4850"]


def test_all_featured_models_present():
    db = load()
    missing = [m for m in FEATURED if db.get(m) is None]
    assert not missing


def test_l3110_family_matches_reference_tools():
    fam = load().get("L3111").family
    # epson_print_conf / reinkpy: read key 0x0797, write key "Maribaya" (wire "Nbsjcbzb")
    assert fam.read_key == [0x97, 0x07]
    assert fam.write_key == "Maribaya"
    assert fam.wire_write_key == b"Nbsjcbzb"
    assert fam.waste_counters[0].max == 6346
    assert fam.waste_reset[0x36] == 0x5E


def test_frames_match_documented_layout():
    fam = load().get("L3111").family
    assert eeprom_read_frame(fam, 0x30).hex() == "7c7c07009707" + "41bea0" + "3000"
    assert eeprom_write_frame(fam, 0x30, 0).hex() == "7c7c10009707" + "42bd21" + "300000" + b"Nbsjcbzb".hex()


def test_detection_keeps_both_l3110_names():
    db = load()
    assert db.detect("L3110 Series").family is db.get("L3111").family
    assert db.detect("L3110 Series", hint="L3111").name == "L3111"
    assert db.detect("L3150 Series").family.name == db.get("L3156").family.name


def test_discharge_job_reproduces_epson_file():
    fam = load().get("L3110").family
    job = pj.scripted_job(fam, "ink_discharge_f2")
    assert len(job) == 1029
    assert job.startswith(bytes.fromhex("1b7c0006009707fb04fd00"))
    assert job.endswith(bytes.fromhex("1b7c0006009707857ac201"))


@pytest.fixture
def session(tmp_path):
    s = PrinterSession.connect("sim:L3111", "L3111")
    s.backup_dir = tmp_path
    yield s
    s.close()


def test_status_and_waste(session):
    st = session.status()
    assert st.state == "Ready" and len(st.inks) == 4
    levels = session.waste_levels()
    assert all(87 <= w.percent <= 88 for w in levels)


def test_reset_requires_ack(session):
    with pytest.raises(SafetyError):
        session.reset_waste(acknowledge_pads_replaced=False)


def test_reset_backup_restore_roundtrip(session, tmp_path):
    before = [w.value for w in session.waste_levels()]
    r = session.reset_waste(acknowledge_pads_replaced=True)
    assert r.ok and r.backup_path.exists()
    assert all(w.value == 0 for w in session.waste_levels())
    doc = json.loads(r.backup_path.read_text())
    assert doc["family"] == "L3AX" and "0x0030" in doc["cells"]
    session.restore(r.backup_path)
    assert [w.value for w in session.waste_levels()] == before


def test_dry_run_never_writes(tmp_path):
    s = PrinterSession.connect("sim:L3111", dry_run=True)
    s.backup_dir = tmp_path
    before = [w.value for w in s.waste_levels()]
    r = s.reset_waste(acknowledge_pads_replaced=True)
    assert r.dry_run and r.messages[0].startswith("DRY RUN")
    assert [w.value for w in s.waste_levels()] == before
    assert not s.link.printer.eeprom_writes


def test_locked_firmware_is_reported():
    from egm.protocol import EepromRefused
    from egm.transport.sim import SimLink
    from egm.protocol import EpsonCtrl
    link = SimLink("L3250", locked=True)
    with pytest.raises(EepromRefused):
        EpsonCtrl(link, load().get("L3250").family).read(0x30)


def test_counters_and_cleaning(session):
    c = session.counters()
    assert c["First TI received time"] == "2024-03-15"
    msg = session.run_cleaning(0, confirm_timeout=8)
    assert "done" in msg and "waste ink counter rose" in msg


@pytest.mark.parametrize("model", ["L3156", "L3250", "L805", "L1800", "ET-2850", "L5290", "L120", "L380"])
def test_featured_models_full_cycle(model, tmp_path):
    s = PrinterSession.connect(f"sim:{model}", model)
    s.backup_dir = tmp_path
    if s.family.coverage != "full":
        pytest.skip(f"{model}: coverage {s.family.coverage}")
    assert s.waste_levels()
    assert s.reset_waste(acknowledge_pads_replaced=True).ok
    assert all(w.value == 0 for w in s.waste_levels())


def test_status_parser_handles_garbage():
    assert parse_status(b"nonsense").parse_error


def test_close_mask_step_applied(tmp_path):
    s = PrinterSession.connect("sim:L3250", "L3250")
    s.backup_dir = tmp_path
    assert s.family.reset_masks == {0x100: 0xFE}
    s.link.eeprom[0x100] = 0xA5
    assert s.reset_waste(acknowledge_pads_replaced=True).ok
    assert s.read(0x100) == 0xA4


# --------------------------------------------------------------------------
#  Reconnect / fallback (field reports: WinErr 5 mid-session, ||:84:NA;)
# --------------------------------------------------------------------------
class _FlakyPrinter:
    """Wraps a simulator link's printer; fails the first N requests like a stale
    Windows handle (AccessDeniedError, WinErr 5)."""

    def __init__(self, inner, fail_times, opens):
        self.inner, self.fail_times, self.opens = inner, fail_times, opens

    def request(self, frame, tries=None):
        from epson_usb.errors import AccessDeniedError
        if self.fail_times[0] > 0:
            self.fail_times[0] -= 1
            raise AccessDeniedError("device I/O failed: WinErr 5 (ACCESS_DENIED)")
        return self.inner.request(frame, tries=tries)

    def describe(self):
        return "flaky"

    def close(self):
        pass


def _flaky_link(fail_times):
    from egm.transport.sim import SimLink
    from egm.transport.usb import UsbLink
    sim = SimLink("L3111")
    opens = []
    counter = [fail_times]

    def factory(path):
        opens.append(path)
        return _FlakyPrinter(sim, counter, opens)
    events = []
    link = UsbLink("\\\\?\\usb#vid_04b8", factory=factory, sleep=lambda s: None, on_event=events.append)
    return link, sim, opens, events


def test_usb_link_reconnects_on_access_denied():
    from egm.protocol import EpsonCtrl
    link, sim, opens, events = _flaky_link(1)
    ctl = EpsonCtrl(link, load().get("L3111").family)
    assert ctl.read(0x30) == sim.eeprom[0x30]
    assert link.reconnects == 1 and len(opens) == 2
    assert any("re-established" in e for e in events)


def test_usb_link_does_not_repeat_service_commands():
    from egm.protocol import EpsonCtrl
    from egm.transport.base import TransportError
    link, sim, opens, events = _flaky_link(1)
    ctl = EpsonCtrl(link, load().get("L3111").family)
    with pytest.raises(TransportError, match="NOT repeated"):
        ctl.service(b"\x04")
    assert link.reconnects == 1
    assert ctl.read(0x30) == sim.eeprom[0x30]  # link usable again


def test_usb_link_gives_up_with_explanation():
    from egm.protocol import EpsonCtrl
    from egm.transport.base import TransportError
    link, sim, opens, events = _flaky_link(10_000)
    with pytest.raises(TransportError, match="spooler"):
        EpsonCtrl(link, load().get("L3111").family).read(0x30)


def test_suspend_then_auto_reopen():
    from egm.protocol import EpsonCtrl
    link, sim, opens, events = _flaky_link(0)
    link.suspend()
    assert EpsonCtrl(link, load().get("L3111").family).read(0x30) == sim.eeprom[0x30]
    assert len(opens) == 2


def test_refused_cleaning_falls_back_to_print_job(tmp_path):
    from egm.operations import ServiceRefused
    s = PrinterSession.connect("sim:L3111", "L3111")
    s.link.printer.refuse_service = True
    with pytest.raises(ServiceRefused):
        s.run_cleaning(3, None)           # fallback disabled
    out = tmp_path / "clean.prn"
    msg = s.run_cleaning(3, f"file:{out}")
    assert "refused" in msg
    assert out.read_bytes() == pj.head_cleaning(power=True)
    assert out.read_bytes().endswith(pj.JOB_TRAILER)


def test_cleaning_reports_why_printer_blocks_it():
    from egm.operations import ServiceRefused
    s = PrinterSession.connect("sim:L3111", "L3111")
    s.link.printer.config.status_extras = ((0x04, bytes([0x51])),)  # "Cleaning disabled (Cyan)"
    with pytest.raises(ServiceRefused, match="Cleaning disabled"):
        s.run_cleaning(1, "file:/dev/null")


def test_print_jobs_end_inside_remote_mode():
    fam = load().get("L3111").family
    for job in (pj.nozzle_check(), pj.nozzle_check(1), pj.head_cleaning(), pj.head_cleaning(power=True),
                pj.release_stuck_job(), pj.color_test_pattern() or pj.nozzle_check()):
        pj.assert_well_formed(job)
        assert job.endswith((pj.EXIT_REMOTE, pj.INIT, pj.JOB_TRAILER))
    # the field bug: JE after the last ESC 00 00 00
    with pytest.raises(ValueError):
        pj.assert_well_formed(pj.EXIT_PACKET_MODE + pj.ENTER_REMOTE + b"NC\x02\x00\x00\x00" + pj.EXIT_REMOTE + pj.JOB_END)
    assert pj.nozzle_check().endswith(b"\x0c\x1b\x00\x1b\x00")


def test_nozzle_check_matches_escputil_bytes():
    # escputil -n with the new (packet-mode) init, from gutenprint escputil.c
    expected = (b"\x00\x00\x00\x1b\x01@EJL 1284.4\n@EJL     \n\x1b@"
                b"\x1b@\x1b(R\x08\x00\x00REMOTE1VI\x02\x00\x00\x00\x1b\x00\x00\x00\x1b\x00"
                b"\x1b@\x1b(R\x08\x00\x00REMOTE1NC\x02\x00\x00\x00\x1b\x00\x00\x00\x1b\x00"
                b"\x0c\x1b\x00\x1b\x00")
    assert pj.nozzle_check() == expected
    assert pj.release_stuck_job().endswith(b"\x0c\x1b\x00\x1b\x00")


def test_close_sends_d4_exit():
    from egm.transport.usb import UsbLink
    sent = []

    class Sess:
        connected = True
        def send(self, psid, ssid, payload, credit=0): sent.append((psid, ssid, payload))
        def recv(self, ms): return None

    class P:
        session = Sess()
        def close(self): sent.append("closed")
        def request(self, f, tries=None): return b""
        def describe(self): return "fake"

    link = UsbLink("x", factory=lambda path: P(), sleep=lambda s: None)
    link.close()
    assert sent == [(0, 0, b"\x08"), "closed"]


def test_cleaning_confirmed_by_waste_counter_when_state_is_invisible():
    s = PrinterSession.connect("sim:L3111", "L3111")
    s.link.printer.report_cleaning_state = False  # like the spooler holding the port
    msg = s.run_cleaning(1, confirm_timeout=12)
    assert "done" in msg and "waste ink counter rose" in msg


def test_confirm_reports_unchanged_counter():
    s = PrinterSession.connect("sim:L3111", "L3111")
    before = s._waste_total()
    ok, why = s.confirm_maintenance(before, timeout=0.5, poll=0.1)
    assert not ok and "did not change" in why


def test_direct_printing_goes_to_the_connected_printer():
    s = PrinterSession.connect("sim:L3111", "L3111")
    msg = s.print_job(pj.nozzle_check())
    assert "simulator" in msg and s.link.printed == [pj.nozzle_check()]


def test_refused_cleaning_falls_back_directly_and_is_confirmed():
    s = PrinterSession.connect("sim:L3111", "L3111")
    s.link.printer.refuse_service = True
    msg = s.run_cleaning(1, confirm_timeout=12)      # default target: direct
    assert "directly to the printer" in msg and "done" in msg
    assert s.link.printed and b"REMOTE1CH" in s.link.printed[-1]


def test_dry_run_does_not_print():
    s = PrinterSession.connect("sim:L3111", dry_run=True)
    assert s.print_job(pj.nozzle_check()).startswith("DRY RUN")
    assert s.link.printed == []


def test_direct_usb_print_writes_raw_and_reopens(monkeypatch):
    """UsbLink.print_raw: closes the control session, writes the job raw, next request reopens."""
    from egm.transport.usb import UsbLink
    written, opened = [], []

    class FakeTransport:
        def write(self, data, timeout_ms=3000): written.append(bytes(data)); return len(data)
        def close(self): pass

    import epson_usb.backends as eb
    monkeypatch.setattr(eb, "open_transport", lambda path, backend=None: FakeTransport())

    class P:
        session = None
        device_info = None
        def request(self, f, tries=None): return b"@BDC ST2"
        def describe(self): return "fake"
        def close(self): pass

    link = UsbLink("\\\\?\\usb#x", factory=lambda path: (opened.append(path), P())[1], sleep=lambda s: None)
    job = pj.nozzle_check()
    assert "directly over USB" in link.print_raw(job, chunk=16)
    assert b"".join(written) == job and link.released
    link.request(b"st\x01\x00\x01")
    assert len(opened) == 2
