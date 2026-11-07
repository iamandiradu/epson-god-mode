# PyInstaller spec -- builds "Epson God Mode" (GUI) and "egm" (CLI).
#
# Windows:  pyinstaller packaging/egm.spec
#   -> dist/EpsonGodMode.exe   (single file, no Python needed)
#   -> dist/egm.exe            (single-file command line tool)
# macOS:    pyinstaller packaging/egm.spec
#   -> dist/Epson God Mode.app
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
PKG = ROOT / "packaging"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

datas = [(str(p), "egm/data") for p in (ROOT / "egm" / "data").glob("*.json")]
hidden = collect_submodules("epson_usb") + ["egm.gui.app"]
if IS_WIN:
    hidden += ["win32print", "win32api", "pywintypes"]
binaries = []

if IS_MAC:
    # bundle libusb so users do not need Homebrew
    try:
        import libusb_package
        lib = libusb_package.get_library_path()
        if lib:
            binaries.append((str(lib), "."))
    except Exception:
        pass

QT_EXCLUDES = ["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
               "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml",
               "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
               "PySide6.QtBluetooth", "PySide6.QtNetworkAuth", "PySide6.QtSql", "PySide6.QtTest",
               "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL", "PySide6.QtSvg"]

gui = Analysis([str(PKG / "gui_entry.py")], pathex=[str(ROOT)], datas=datas, hiddenimports=hidden,
               binaries=binaries, excludes=QT_EXCLUDES)
cli = Analysis([str(PKG / "cli_entry.py")], pathex=[str(ROOT)], datas=datas, hiddenimports=hidden,
               binaries=binaries, excludes=["tkinter", "PySide6"])
gui_pyz = PYZ(gui.pure)
cli_pyz = PYZ(cli.pure)

icon = str(PKG / ("icon.ico" if IS_WIN else "icon.png"))
version = str(PKG / "version_info.txt") if IS_WIN else None

import os
# macOS signing: set EGM_MAC_SIGN_IDENTITY to "Developer ID Application: Name (TEAMID)" to sign
# with the hardened runtime (required for notarization).  Unset -> ad-hoc signature.
MAC_IDENTITY = os.environ.get("EGM_MAC_SIGN_IDENTITY") or None
MAC_ENTITLEMENTS = str(PKG / "macos" / "entitlements.plist") if MAC_IDENTITY else None

if IS_MAC:
    # .app bundles must be one-dir
    gui_exe = EXE(gui_pyz, gui.scripts, [], exclude_binaries=True, name="EpsonGodMode", console=False, icon=icon,
                  codesign_identity=MAC_IDENTITY, entitlements_file=MAC_ENTITLEMENTS)
    cli_exe = EXE(cli_pyz, cli.scripts, [], exclude_binaries=True, name="egm", console=True,
                  codesign_identity=MAC_IDENTITY, entitlements_file=MAC_ENTITLEMENTS)
    coll = COLLECT(gui_exe, gui.binaries, gui.datas, cli_exe, cli.binaries, cli.datas, name="EpsonGodMode")
    app = BUNDLE(coll, name="Epson God Mode.app", icon=icon, bundle_identifier="ro.iamandi.epsongodmode",
                 info_plist={"NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0",
                             "CFBundleShortVersionString": "0.1.0"})
else:
    # single-file executables: copy one .exe anywhere and run it
    EXE(gui_pyz, gui.scripts, gui.binaries, gui.datas, [], name="EpsonGodMode", console=False,
        icon=icon, version=version, upx=False, runtime_tmpdir=None)
    EXE(cli_pyz, cli.scripts, cli.binaries, cli.datas, [], name="egm", console=True,
        icon=icon, version=version, upx=False)
