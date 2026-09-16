"""Configure the Windows DLL search path for the frozen Qt application."""

import os
import sys


if sys.platform == "win32":
    bundle_root = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    for directory in (bundle_root, os.path.join(bundle_root, "PySide6")):
        if os.path.isdir(directory):
            os.add_dll_directory(directory)
