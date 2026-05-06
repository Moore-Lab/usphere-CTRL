"""
Run once to create a Windows desktop shortcut for fpga_gui.py.

    python create_shortcut.py

Requires: pywin32  (pip install pywin32)

Python resolution order
-----------------------
1. .venv/ inside this project directory  (created by install_deps.py)
2. ../usphere-FPGA/.venv/  (shared sibling venv with pylablib)
3. The Python that ran this script  (sys.executable)

If you see KCube or pylablib errors after launching via the shortcut, run
install_deps.py first to create a local venv, then re-run this script.
"""

import sys
from pathlib import Path

try:
    from win32com.client import Dispatch
except ImportError:
    print("pywin32 is required.  Install it with:\n  pip install pywin32")
    sys.exit(1)

PROJECT_DIR = Path(__file__).resolve().parent
SCRIPT      = PROJECT_DIR / "fpga_gui.py"
ICON        = PROJECT_DIR / "assets" / "uCTRL_logo.ico"

_shell        = Dispatch("WScript.Shell")
DESKTOP       = Path(_shell.SpecialFolders("Desktop"))
SHORTCUT_PATH = DESKTOP / "usphere CTRL.lnk"


def _find_python() -> str:
    """Return the best available pythonw.exe / python.exe path."""
    candidates = [
        # 1. Local project venv (install_deps.py creates this)
        PROJECT_DIR / ".venv" / "Scripts" / "pythonw.exe",
        PROJECT_DIR / ".venv" / "Scripts" / "python.exe",
        # 2. Sibling usphere-FPGA venv (already has pylablib)
        PROJECT_DIR.parent.parent / "usphere-FPGA" / ".venv" / "Scripts" / "pythonw.exe",
        PROJECT_DIR.parent.parent / "usphere-FPGA" / ".venv" / "Scripts" / "python.exe",
    ]
    for c in candidates:
        if c.exists():
            print(f"  Using Python: {c}")
            return str(c)

    # 3. Fallback: whatever ran this script
    fallback = Path(sys.executable).parent / "pythonw.exe"
    chosen = str(fallback if fallback.exists() else sys.executable)
    print(f"  Using Python (fallback — pylablib may be missing): {chosen}")
    return chosen


python_exe = _find_python()

shortcut = _shell.CreateShortCut(str(SHORTCUT_PATH))
shortcut.TargetPath       = python_exe
shortcut.Arguments        = f'"{SCRIPT}"'
shortcut.WorkingDirectory = str(PROJECT_DIR)
shortcut.Description      = "usphere FPGA Control"
shortcut.IconLocation     = str(ICON) if ICON.exists() else python_exe
shortcut.save()

print(f"Shortcut created: {SHORTCUT_PATH}")
