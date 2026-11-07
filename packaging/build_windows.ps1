# Build the Windows executables (same as build_exe.bat). Run from the repository root.
$ErrorActionPreference = "Stop"
if (-not (Test-Path .venv)) { py -3 -m venv .venv }
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".[patterns,dev]" pywin32
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m PyInstaller --noconfirm --clean packaging\egm.spec
Compress-Archive -Force -Path dist\EpsonGodMode.exe, dist\egm.exe, README.md, LICENSE -DestinationPath dist\EpsonGodMode-windows.zip
Write-Host "Built dist\EpsonGodMode.exe, dist\egm.exe and dist\EpsonGodMode-windows.zip"
