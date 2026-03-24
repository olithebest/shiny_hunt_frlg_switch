@echo off
echo ===================================================
echo   Shiny Hunter FRLG Switch — Setup
echo ===================================================
echo.

echo [1/3] Checking Python installation...
python --version 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Python not found!
    echo Please install Python 3.10 or newer from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo [2/3] Upgrading pip...
python -m pip install --upgrade pip

echo.
echo [3/3] Installing dependencies...
pip install -r requirements.txt

echo.
echo ===================================================
echo   Setup complete! Run start.bat to launch the app.
echo ===================================================
pause
