# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller untuk Noktah.

Mode dipilih lewat env var:
    NOKTah_ONEDIR tidak diset -> onefile (satu Noktah.exe)
    NOKTah_ONEDIR=1           -> onedir (folder portable, start lebih cepat)

Build lewat:  py -3.10 build_tools/build.py [--onedir]
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ONEDIR = os.environ.get("NOKTAH_ONEDIR") == "1"

SPEC_DIR = os.path.abspath(SPECPATH)
ROOT = os.path.dirname(SPEC_DIR)
SCRIPT = os.path.join(ROOT, "noktah.py")
ICON = os.path.join(ROOT, "assets", "noktah.ico")
VERSION = os.path.join(SPEC_DIR, "noktah-version.txt")

# winsdk memuat modul WinRT secara dinamis -> paksa ikut semuanya.
winsdk_datas, winsdk_binaries, winsdk_hidden = collect_all("winsdk")
extra_hidden = []
try:
    extra_hidden += collect_submodules("winsdk.windows.media")
    extra_hidden += collect_submodules("winsdk.windows.storage")
except Exception:
    pass

a = Analysis(
    [SCRIPT],
    pathex=[],
    binaries=winsdk_binaries,
    datas=winsdk_datas,
    hiddenimports=winsdk_hidden + extra_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtQuickWidgets",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "PySide6.QtSerialPort",
        "PySide6.QtBluetooth",
        "PySide6.QtPositioning",
        "PySide6.QtSensors",
        "PySide6.QtNfc",
        "PySide6.QtWebChannel",
        "PySide6.QtWebSockets",
        "PySide6.QtNetworkAuth",
        "PySide6.QtSpatialAudio",
        "PySide6.QtTextToSpeech",
        "PySide6.QtScxml",
        "PySide6.QtStateMachine",
        "PySide6.QtRemoteObjects",
        "PySide6.QtHttpServer",
        "PySide6.QtGraphs",
        "pythonnet",
        "numpy",
        "PIL",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe_kwargs = dict(
    name="Noktah",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
    version=VERSION,
)

if ONEDIR:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        **exe_kwargs,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="Noktah",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        **exe_kwargs,
    )
