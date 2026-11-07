@echo off
REM Quick start on Windows without building: installs deps in a local venv and starts the GUI.
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -e ".[patterns]"
)
if "%1"=="" (
  .venv\Scripts\python -m egm gui
) else (
  .venv\Scripts\python -m egm %*
)
