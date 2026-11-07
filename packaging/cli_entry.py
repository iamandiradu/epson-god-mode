import os, sys
if sys.platform == "darwin" and getattr(sys, "frozen", False):
    # point epson-usb at the bundled libusb
    base = os.path.dirname(sys.executable)
    for cand in (os.path.join(base, "libusb-1.0.dylib"), os.path.join(base, "..", "Frameworks", "libusb-1.0.dylib")):
        if os.path.exists(cand):
            os.environ.setdefault("EPSON_USB_LIBUSB", os.path.abspath(cand))
            break
from egm.cli import main as run
sys.exit(run())
