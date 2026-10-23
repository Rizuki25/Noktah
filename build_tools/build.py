"""Build Noktah jadi .exe.

Pakai:
    py -3.10 build_tools/build.py            # onefile (satu .exe)
    py -3.10 build_tools/build.py --onedir   # folder portable (start lebih cepat)

Hasil ada di dist/.
"""

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "build_tools", "noktah.spec")
DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build")


def run(cmd, env=None):
    print("$", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT, env=env)


def ensure_icon():
    ico = os.path.join(ROOT, "assets", "noktah.ico")
    if os.path.exists(ico):
        return True
    print("membuat ikon...")
    code = run([sys.executable, os.path.join(ROOT, "build_tools", "make_icon.py")])
    return code == 0 and os.path.exists(ico)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--onedir", action="store_true", help="build folder, bukan onefile")
    parser.add_argument("--clean", action="store_true", help="hapus build/ dan dist/ dulu")
    args = parser.parse_args()

    if args.clean:
        for path in (DIST, WORK):
            if os.path.isdir(path):
                print("hapus", path)
                shutil.rmtree(path, ignore_errors=True)

    if not ensure_icon():
        print("GAGAL: ikon tidak bisa dibuat")
        return 1

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", SPEC]
    env = dict(os.environ)
    if args.onedir:
        env["NOKTAH_ONEDIR"] = "1"
    else:
        env.pop("NOKTAH_ONEDIR", None)

    code = run(cmd, env=env)
    if code != 0:
        print("BUILD GAGAL (exit %s)" % code)
        return code

    target = os.path.join(DIST, "Noktah.exe")
    if os.path.exists(target):
        size = os.path.getsize(target) / (1024 * 1024)
        print(f"\nOK -> {target}  ({size:.1f} MB)")
    else:
        print("\nSelesai, cek isi dist/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
