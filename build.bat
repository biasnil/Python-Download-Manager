@echo off
rem ================================================================
rem  PyDM - build for Windows
rem    Double-click it, or run from PowerShell / cmd:   .\build.bat
rem    Options:  --no-pause   (don't wait for a key at the end)
rem  Output: dist\PyDM\PyDM.exe
rem ================================================================
setlocal
cd /d "%~dp0"
echo.
echo === PyDM build (Windows) ===
echo.

set "VENV=.venv"
set "PYEXE=%VENV%\Scripts\python.exe"
if exist "%PYEXE%" goto :have_venv

rem --- pick a Python: the "py" launcher first, then "python" ---
set "PY=python"
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found. Install Python 3.10+ from python.org
    echo        and tick "Add python.exe to PATH".
    goto :fail
)
echo [1/4] Creating virtual environment in %VENV% ...
%PY% -m venv "%VENV%"
if errorlevel 1 goto :fail

:have_venv
echo [2/4] Installing requirements + PyInstaller ...
"%PYEXE%" -m pip install --upgrade pip --quiet
"%PYEXE%" -m pip install -r requirements.txt pyinstaller --quiet
if errorlevel 1 goto :fail

echo [3/4] Cleaning old build ...
if exist build rmdir /s /q build
if exist dist\PyDM rmdir /s /q dist\PyDM

echo [4/4] Building with PyDM.spec ...
"%PYEXE%" -m PyInstaller PyDM.spec --noconfirm --log-level WARN
if errorlevel 1 goto :fail
if not exist dist\PyDM\PyDM.exe goto :fail

echo.
echo ================================================================
echo  Done:  %CD%\dist\PyDM\PyDM.exe
echo  Browser extension:  dist\PyDM\extension  (Load unpacked in Chrome)
echo ================================================================
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo.
    echo NOTE: ffmpeg was not found. HD YouTube and MP3 need it:
    echo       winget install Gyan.FFmpeg
)
if /i not "%~1"=="--no-pause" (
    start "" explorer "dist\PyDM"
    pause
)
exit /b 0

:fail
echo.
echo *** BUILD FAILED - see the messages above ***
if /i not "%~1"=="--no-pause" pause
exit /b 1
