#!/usr/bin/env bash
# ================================================================
#  PyDM - build for Linux
#    chmod +x build.sh   (once)
#    ./build.sh
#  Output: dist/PyDM/PyDM
# ================================================================
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
VENV=".venv"
PYEXE="$VENV/bin/python"

echo
echo "=== PyDM build (Linux) ==="
echo

if [ ! -x "$PYEXE" ]; then
    if ! command -v "$PY" >/dev/null 2>&1; then
        echo "ERROR: $PY not found. Install it, e.g.: sudo apt install python3 python3-venv"
        exit 1
    fi
    echo "[1/4] Creating virtual environment in $VENV ..."
    if ! "$PY" -m venv "$VENV"; then
        echo "ERROR: couldn't create the venv. On Debian/Ubuntu: sudo apt install python3-venv"
        exit 1
    fi
fi

echo "[2/4] Installing requirements + PyInstaller ..."
"$PYEXE" -m pip install --upgrade pip --quiet
"$PYEXE" -m pip install -r requirements.txt pyinstaller --quiet

echo "[3/4] Cleaning old build ..."
rm -rf build dist/PyDM

echo "[4/4] Building with PyDM.spec ..."
"$PYEXE" -m PyInstaller PyDM.spec --noconfirm --log-level WARN

if [ ! -x dist/PyDM/PyDM ]; then
    echo; echo "*** BUILD FAILED - see the messages above ***"; exit 1
fi

echo
echo "================================================================"
echo " Done:  $(pwd)/dist/PyDM/PyDM"
echo " Browser extension:  dist/PyDM/extension  (Load unpacked in Chrome)"
echo "================================================================"
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo; echo "NOTE: ffmpeg not found. HD YouTube and MP3 need it:  sudo apt install ffmpeg"
fi
# Qt 6 on X11 needs this library at run time
if command -v ldconfig >/dev/null 2>&1 && ! ldconfig -p | grep -q "libxcb-cursor.so.0"; then
    echo; echo "NOTE: Qt needs libxcb-cursor0 to open windows:  sudo apt install libxcb-cursor0"
fi
