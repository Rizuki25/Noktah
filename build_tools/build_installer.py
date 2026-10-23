"""Build installer mandiri Noktah (dist/Noktah-Setup-1.0.0.exe) tanpa Inno Setup.

Installer dikompilasi menggunakan C# compiler bawaan Windows (.NET Framework csc.exe)
dengan bundel zip di dalam memori resource executable, sehingga:
- TIDAK membuat folder sementara (is-XXXX.tmp / _MEIxxxx) di %TEMP% saat dijalankan.
- TIDAK terkena blokir Error 5: Access is denied pada %TEMP%.
- TIDAK membutuhkan hak Administrator (berjalan per-user ke %LOCALAPPDATA%\\Programs\\Noktah).
- Menyertakan GUI modern serta Uninstall-Noktah.exe.

Prasyarat:
    dist\\Noktah\\ sudah ada -> py -3.10 build_tools/build.py --onedir

Pakai:
    py -3.10 build_tools/build_installer.py
"""

import os
import shutil
import subprocess
import sys
import zipfile

APP_VERSION = "1.0.0"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "dist", "Noktah")
OUT_DIR = os.path.join(ROOT, "dist")
WORK_DIR = os.path.join(ROOT, "build", "installer_work")
CS_SRC = os.path.join(ROOT, "build_tools", "SetupProgram.cs")
ICON_PATH = os.path.join(ROOT, "assets", "noktah.ico")
LOGO_PATH = os.path.join(ROOT, "assets", "noktah.png")

CSC_CANDIDATES = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), r"Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), r"Microsoft.NET\Framework\v4.0.30319\csc.exe"),
]

MANIFEST_XML = """<?xml version="1.0" encoding="utf-8"?>
<assembly manifestVersion="1.0" xmlns="urn:schemas-microsoft-com:asm.v1">
  <assemblyIdentity version="1.0.0.0" name="Rizuki25.Noktah.Setup"/>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v2">
    <security>
      <requestedPrivileges xmlns="urn:schemas-microsoft-com:asm.v3">
        <requestedExecutionLevel level="asInvoker" uiAccess="false" />
      </requestedPrivileges>
    </security>
  </trustInfo>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/PM</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2, PerMonitor</dpiAwareness>
    </windowsSettings>
  </application>
</assembly>
"""


def find_csc():
    for path in CSC_CANDIDATES:
        if os.path.exists(path):
            return path
    return shutil.which("csc")


def create_payload_zip(zip_path, app_dir, uninstaller_exe):
    print("Membuat paket payload.zip dari dist\\Noktah ...")
    count = 0
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, _dirs, files in os.walk(app_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, app_dir).replace("\\", "/")
                if rel_path.lower() == "uninstall-noktah.exe":
                    continue
                zf.write(full_path, rel_path)
                count += 1
        if os.path.exists(uninstaller_exe):
            zf.write(uninstaller_exe, "Uninstall-Noktah.exe")
            count += 1
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"  -> {count} file dikemas ({size_mb:.1f} MB)")


def run_csc(cmd, work_dir):
    env = dict(os.environ)
    env["TEMP"] = work_dir
    env["TMP"] = work_dir
    print("$", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT, env=env)


def main():
    if not os.path.isdir(APP_DIR) or not os.path.exists(os.path.join(APP_DIR, "Noktah.exe")):
        print("Folder dist\\Noktah\\Noktah.exe belum ada.")
        print("Jalankan dulu:  py -3.10 build_tools/build.py --onedir")
        return 1

    csc = find_csc()
    if not csc:
        print("ERROR: csc.exe (.NET Framework 4.x) tidak ditemukan di Windows.")
        return 1

    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    manifest_path = os.path.join(WORK_DIR, "app.manifest")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(MANIFEST_XML)

    refs = [
        "/r:System.dll",
        "/r:System.Drawing.dll",
        "/r:System.Windows.Forms.dll",
        "/r:System.IO.Compression.dll",
        "/r:System.IO.Compression.FileSystem.dll",
    ]

    # 1. Compile uninstaller ringan (tanpa payload 50MB)
    uninstaller_out = os.path.join(WORK_DIR, "Uninstall-Noktah.exe")
    unins_cmd = [
        csc,
        "/nologo",
        "/optimize+",
        "/target:winexe",
        f"/out:{uninstaller_out}",
        f"/win32manifest:{manifest_path}",
    ]
    if os.path.exists(ICON_PATH):
        unins_cmd.append(f"/win32icon:{ICON_PATH}")
    unins_cmd.extend(refs)
    unins_cmd.append(CS_SRC)

    print("Mengompilasi Uninstall-Noktah.exe ...")
    rc = run_csc(unins_cmd, WORK_DIR)
    if rc != 0:
        print(f"GAGAL mengompilasi Uninstall-Noktah.exe (exit {rc})")
        return rc

    # Salin juga Uninstall-Noktah.exe ke dist\Noktah
    try:
        shutil.copy2(uninstaller_out, os.path.join(APP_DIR, "Uninstall-Noktah.exe"))
    except OSError:
        pass

    # 2. Buat payload.zip dari dist\Noktah + Uninstall-Noktah.exe
    payload_zip = os.path.join(WORK_DIR, "payload.zip")
    create_payload_zip(payload_zip, APP_DIR, uninstaller_out)

    # 3. Compile Noktah-Setup-1.0.0.exe dengan resource payload.zip & logo
    setup_out = os.path.join(OUT_DIR, f"Noktah-Setup-{APP_VERSION}.exe")
    setup_cmd = [
        csc,
        "/nologo",
        "/optimize+",
        "/target:winexe",
        f"/out:{setup_out}",
        f"/win32manifest:{manifest_path}",
        f"/resource:{payload_zip},Noktah.Payload.zip",
    ]
    if os.path.exists(ICON_PATH):
        setup_cmd.append(f"/win32icon:{ICON_PATH}")
    if os.path.exists(LOGO_PATH):
        setup_cmd.append(f"/resource:{LOGO_PATH},Noktah.Logo.png")
    setup_cmd.extend(refs)
    setup_cmd.append(CS_SRC)

    print(f"Mengompilasi {os.path.basename(setup_out)} ...")
    rc = run_csc(setup_cmd, WORK_DIR)
    if rc != 0:
        print(f"GAGAL mengompilasi {setup_out} (exit {rc})")
        return rc

    # Bersihkan file kerja sementara
    try:
        shutil.rmtree(WORK_DIR, ignore_errors=True)
    except OSError:
        pass

    # Pastikan file installer memiliki label Medium Integrity (bukan Low Integrity)
    subprocess.call(
        ["icacls.exe", setup_out, "/setintegritylevel", "Medium"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    size = os.path.getsize(setup_out) / (1024 * 1024)
    print(f"\nOK -> {setup_out}  ({size:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
