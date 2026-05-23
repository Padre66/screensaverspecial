@echo off
setlocal

cd /d %~dp0

echo Creating virtual environment...
if not exist .venv (
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo Building EXE...
pyinstaller --noconfirm --onefile --windowed --name ScreenSaverSpecial screensaver_special.py

echo.
echo Done.
echo EXE location: dist\ScreenSaverSpecial.exe
echo.
pause
