@echo off
REM Builds dist\EpsonGodMode.exe (and dist\egm.exe) -- standalone, no Python needed to RUN them.
REM Building needs Python once (the same one run_windows.bat uses).
setlocal
cd /d "%~dp0"
if not exist .venv (
  echo Creating build environment...
  py -3 -m venv .venv || (echo Python 3.10+ is required to build: https://www.python.org/downloads/ & pause & exit /b 1)
)
echo Installing build tools...
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -e ".[patterns]" pyinstaller pywin32 || (echo Dependency install failed. & pause & exit /b 1)
echo Building (takes a few minutes)...
if exist build rmdir /s /q build
.venv\Scripts\python -m PyInstaller --noconfirm --clean packaging\egm.spec || (echo Build failed - see messages above. & pause & exit /b 1)
echo.
if exist signing.env.bat call signing.env.bat
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\sign_windows.ps1 || (echo Code signing failed - see messages above. & pause & exit /b 1)
echo.
echo Smoke test of the built command line tool:
dist\egm.exe -d sim:L3111 waste || (echo Smoke test failed. & pause & exit /b 1)
echo.
echo Done:
echo   dist\EpsonGodMode.exe   - the app (copy it anywhere, no Python needed)
echo   dist\egm.exe            - command line version
explorer dist
pause
