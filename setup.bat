@echo off
REM Run this from inside the asos-export folder (double-click it in
REM File Explorer, or run "setup.bat" from Command Prompt already
REM in this folder). It creates the virtual environment if it doesn't
REM exist yet, installs/updates dependencies, and applies any pending
REM database migrations -- the same three steps you'd otherwise type
REM by hand every time you get an updated copy of the project.

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Installing/updating dependencies...
pip install -e ".[dev]"

echo Applying database updates...
asos init-db

echo.
echo Done. The virtual environment is active in THIS window --
echo run "asos" commands directly from here. If you open a new
echo Command Prompt window later, you'll still need to run:
echo     .venv\Scripts\activate
echo before using asos again in that new window.
pause
