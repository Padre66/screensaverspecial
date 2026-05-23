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
pyinstaller --noconfirm screensaverspecial.spec

echo Preparing package folder...
if exist package rmdir /s /q package
mkdir package
copy dist\ScreenSaverSpecial.exe package\ScreenSaverSpecial.exe
copy config.json package\config.json
copy config.example.json package\config.example.json

echo.
echo Done.
echo Package location: package\
echo EXE location: package\ScreenSaverSpecial.exe
echo Config location: package\config.json
echo.
pause
