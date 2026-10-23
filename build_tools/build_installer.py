"""Build installer Noktah (Noktah-Setup-x.y.z.exe) dengan Inno Setup.

Prasyarat:
    1. dist\\Noktah\\  sudah ada  ->  py -3.10 build_tools/build.py --onedir
    2. Inno Setup 6 terpasang    ->  winget install JRSoftware.InnoSetup

Pakai:
    py -3.10 build_tools/build_installer.py
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISS = os.path.join(ROOT, "build_tools", "noktah.iss")
APP_DIR = os.path.join(ROOT, "dist", "Noktah")
OUT_DIR = os.path.join(ROOT, "dist")

CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def find_iscc():
    for path in CANDIDATES:
        if os.path.exists(path):
            return path
    found = shutil.which("iscc") or shutil.which("ISCC")
    return found


def main():
    if not os.path.isdir(APP_DIR):
        print("Folder dist\\Noktah belum ada.")
        print("Jalankan dulu:  py -3.10 build_tools/build.py --onedir")
        return 1

    iscc = find_iscc()
    if not iscc:
        print("ISCC.exe (Inno Setup) tidak ditemukan.")
        print("Pasang dulu:  winget install JRSoftware.InnoSetup")
        return 1

    print("ISCC:", iscc)
    cmd = [iscc, "/Qp", ISS]
    print("$", " ".join(cmd))
    code = subprocess.call(cmd, cwd=ROOT)
    if code != 0:
        print("BUILD INSTALLER GAGAL (exit %s)" % code)
        return code

    for name in os.listdir(OUT_DIR):
        if name.lower().startswith("noktah-setup") and name.lower().endswith(".exe"):
            path = os.path.join(OUT_DIR, name)
            size = os.path.getsize(path) / (1024 * 1024)
            print(f"\nOK -> {path}  ({size:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
