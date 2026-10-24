# noktah.py — Noktah: notch pemutar musik untuk Windows 10/11
#
# Menampilkan lagu yang sedang diputar di browser (YouTube Music, YouTube,
# Spotify Web, dll) lewat jalur resmi Windows Media Session (SMTC) — jalur
# yang sama yang dipakai tombol media di keyboard dan flyout volume Windows.
#
# Tampilan: panel hitam yang MENEMPEL ke tepi atas layar. Saat ringkas ia
# jadi tab kecil berisi sampul + equalizer; saat disorot (atau saat lagu
# berganti) ia turun membesar dengan animasi pegas dan menampilkan jam &
# tanggal, judul, artis, bilah progres, serta dock tombol
# prev / play-pause / next. Warna aksen (glow, equalizer, progres) diambil
# dari sampul album yang sedang diputar.
#
# Indikator privasi: titik oranye (mikrofon) / hijau (kamera) seperti di
# iPhone, selalu kelihatan walau panel ringkas. Nama aplikasi yang sedang
# memakai perangkat dibaca dari registry CapabilityAccessManager.
#
# Baterai: ikon baterai sungguhan di header (isinya mengikuti persen), pil
# berdenyut hijau sebentar saat charger dicolok, dan badge berganti jadi
# peringatan saat baterai tinggal <= 15% — semuanya dari GetSystemPowerStatus.
#
# Persiapan (sekali saja):
#   py -3.10 -m pip install PySide6 winsdk
#
# Jalankan:
#   py -3.10 noktah.py
#   (atau klik dua kali run_noktah.bat)
#
# Kontrol:
#   sorot panel        -> membesar (expanded)
#   klik kiri (ringkas)-> play / pause
#   seret              -> geser; dilepas -> menempel lagi ke tepi atas
#   klik bilah progres -> lompat ke posisi itu
#   klik kanan         -> menu Keluar / Tempel ke atas / Indikator mic-kamera
#   Spasi / <- / ->    -> play-pause / prev / next (saat notch terfokus)
#   Esc                -> keluar

import asyncio
import ctypes
from ctypes import wintypes
import hashlib
import math
import os
import queue
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

try:  # hanya ada di Windows; dijaga supaya modul tetap bisa diimpor saat uji
    import winreg
except ImportError:  # pragma: no cover
    winreg = None

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QObject,
    QPointF,
    QRectF,
    QSettings,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

# --- API media Windows (SMTC) lewat winsdk; fallback ke paket winrt baru ---
try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    )
    from winsdk.windows.storage.streams import Buffer, DataReader, InputStreamOptions
except ImportError:  # paket PyWinRT generasi baru
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    )
    from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions

STATUS_PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING

# --- Geometri pil (tanpa margin bayangan) ---
COLLAPSED_W, COLLAPSED_H = 114.0, 38.0
EXPANDED_W, EXPANDED_H = 556.0, 162.0
MARGIN = 36.0  # ruang untuk lekuk telinga atas & bayangan di sekeliling pil

# Jendela selalu sebesar keadaan membesar dan TIDAK pernah di-resize saat
# animasi. Mengubah ukuran jendela translucent tiap frame membuat Windows
# menahan render (frame drop); jadi hanya lukisannya yang beranimasi.
# Margin hanya di kiri/kanan/bawah: sisi atas menempel ke tepi layar.
WIN_W = EXPANDED_W + 2 * MARGIN
WIN_H = EXPANDED_H + MARGIN

ACCENT_FALLBACK = QColor(218, 168, 118)

# --- Indikator mic/kamera: titik oranye & hijau ala iPhone ---
MIC_COLOR = QColor(255, 159, 10)   # oranye: mikrofon sedang dipakai
CAM_COLOR = QColor(48, 209, 88)    # hijau: kamera sedang dipakai
PRIVACY_POLL_SEC = 0.75            # jeda antar pembacaan registry

# --- Baterai: ikon asli di header, denyut hijau saat charger dicolok ---
BATTERY_POLL_MS = 3000     # GetSystemPowerStatus murah; 3 detik sudah cukup
BATTERY_LOW = 15           # persen: di bawah/nyampe ini muncul peringatan
BATTERY_WARN_SEC = 12.0    # lama teks peringatan menempati badge
CHARGE_PULSE_SEC = 4.0     # lama pil berdenyut hijau setelah charger dicolok

CHARGE_COLOR = QColor(48, 209, 88)
LOW_COLOR = QColor(255, 69, 58)
MID_COLOR = QColor(255, 176, 32)
BATT_LEVEL_COLOR = QColor(226, 205, 180)


# ---------------------------------------------------------------- utilitas --
def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(edge0, edge1, x):
    if edge1 == edge0:
        return 0.0 if x < edge0 else 1.0
    t = clamp((x - edge0) / (edge1 - edge0))
    return t * t * (3.0 - 2.0 * t)


def fmt_time(seconds):
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class Spring:
    """Pegas-redam sederhana supaya gerakannya terasa seperti iOS, bukan linear."""

    __slots__ = ("value", "target", "vel", "k", "c")

    def __init__(self, value=0.0, k=200.0, c=26.0):
        self.value = float(value)
        self.target = float(value)
        self.vel = 0.0
        self.k = k
        self.c = c

    def jump(self, value):
        self.value = float(value)
        self.vel = 0.0

    def step(self, dt):
        accel = (self.target - self.value) * self.k - self.vel * self.c
        self.vel += accel * dt
        self.value += self.vel * dt

    def settled(self, eps=0.0008):
        return abs(self.target - self.value) < eps and abs(self.vel) < eps * 8


# ------------------------------------------------------------------- bridge --
class MediaBridge(QObject):
    """Mengurus semua komunikasi dengan Windows Media Session di thread lain."""

    updated = Signal(dict)

    def __init__(self):
        super().__init__()
        self._cmds = queue.Queue()
        self._thumb_key = None
        self._thumb = None
        self._pos_key = None
        self._last_raw_pos = -1.0
        self._last_upd_iso = None
        self._anchor_pos = 0.0
        self._anchor_mono = time.monotonic()

    def start(self):
        threading.Thread(target=self._thread_main, daemon=True).start()

    def enqueue(self, cmd):
        self._cmds.put(cmd)

    def _thread_main(self):
        asyncio.run(self._run())

    async def _run(self):
        manager = None
        session = None
        while True:
            try:
                if manager is None:
                    manager = await SessionManager.request_async()

                # Jalankan perintah dari UI (tombol & seek)
                while True:
                    try:
                        cmd = self._cmds.get_nowait()
                    except queue.Empty:
                        break
                    if session is None:
                        continue
                    if isinstance(cmd, tuple) and cmd[0] == "seek":
                        target_sec = max(0.0, float(cmd[1]))
                        self._anchor_pos = target_sec
                        self._anchor_mono = time.monotonic()
                        try:
                            # WinRT TryChangePlaybackPositionAsync menerima Int64
                            # dalam satuan 100-nanodetik (ticks)
                            ticks = int(round(target_sec * 10_000_000))
                            await session.try_change_playback_position_async(ticks)
                        except TypeError:
                            try:
                                await session.try_change_playback_position_async(
                                    timedelta(seconds=target_sec)
                                )
                            except Exception:
                                pass
                        except Exception:
                            pass
                    elif cmd == "toggle":
                        await session.try_toggle_play_pause_async()
                    elif cmd == "next":
                        await session.try_skip_next_async()
                    elif cmd == "prev":
                        await session.try_skip_previous_async()

                session = manager.get_current_session()
                data = await self._read(session)
                self.updated.emit(data)
            except Exception:  # jangan mati hanya karena satu sesi aneh
                self.updated.emit(
                    {
                        "title": "Paper Sky",
                        "artist": "Lumen Coast - Summer Flows",
                        "status": 0,
                        "pos": 193.0,
                        "dur": 256.0,
                        "thumb": None,
                    }
                )
                manager = None
                session = None
            await asyncio.sleep(0.5)

    async def _read(self, session):
        if session is None:
            return {
                "title": "Paper Sky",
                "artist": "Lumen Coast - Summer Flows",
                "status": 0,
                "pos": 193.0,
                "dur": 256.0,
                "thumb": None,
            }
        props = await session.try_get_media_properties_async()
        info = session.get_playback_info()
        status = int(info.playback_status)
        playing = status == STATUS_PLAYING

        timeline = session.get_timeline_properties()
        raw_pos = timeline.position.total_seconds() if timeline.position else 0.0
        dur = 0.0
        if timeline.end_time and timeline.start_time:
            dur = (timeline.end_time - timeline.start_time).total_seconds()
        if dur <= 0 and timeline.end_time:
            dur = timeline.end_time.total_seconds()
        if dur <= 0:
            # sebagian sesi (mis. YouTube di Edge) hanya mengisi max_seek_time
            try:
                dur = timeline.max_seek_time.total_seconds()
            except Exception:
                dur = 0.0

        key = (props.title, props.artist)

        # Hitung posisi aktual secara presisi:
        # SMTC hanya memperbarui timeline.position saat lagu mulai / seek / pause,
        # lalu mencatat waktu pembaruannya di timeline.last_updated_time (UTC).
        last_upd = getattr(timeline, "last_updated_time", None)
        upd_iso = None
        elapsed_from_smtc = None
        if last_upd is not None:
            try:
                if last_upd.tzinfo is None:
                    last_upd = last_upd.replace(tzinfo=timezone.utc)
                upd_iso = last_upd.isoformat()
                diff_sec = (datetime.now(timezone.utc) - last_upd).total_seconds()
                # Pastikan timestamp valid (bukan epoch 1601-01-01 milik WinRT)
                if 0.0 <= diff_sec < 36000.0:
                    elapsed_from_smtc = diff_sec
            except Exception:
                elapsed_from_smtc = None

        now_mono = time.monotonic()
        if elapsed_from_smtc is not None:
            pos = raw_pos + (elapsed_from_smtc if playing else 0.0)
            self._pos_key = key
            self._last_raw_pos = raw_pos
            self._last_upd_iso = upd_iso
            self._anchor_pos = pos
            self._anchor_mono = now_mono
        else:
            # Fallback bila player tidak mengisi last_updated_time dengan benar
            snapshot_changed = (
                key != self._pos_key
                or abs(raw_pos - self._last_raw_pos) > 0.5
                or (upd_iso is not None and upd_iso != self._last_upd_iso)
            )
            if snapshot_changed:
                self._pos_key = key
                self._last_raw_pos = raw_pos
                self._last_upd_iso = upd_iso
                self._anchor_pos = raw_pos
                self._anchor_mono = now_mono
                pos = raw_pos
            elif playing:
                pos = self._anchor_pos + (now_mono - self._anchor_mono)
            else:
                pos = self._anchor_pos
                self._anchor_mono = now_mono

        if dur > 0:
            pos = clamp(pos, 0.0, dur)
        else:
            pos = max(0.0, pos)

        # Ambil gambar album hanya saat lagunya berganti
        if key != self._thumb_key:
            self._thumb_key = key
            self._thumb = await self._fetch_thumb(props)

        artist = (props.artist or "").strip()
        album = (getattr(props, "album_title", "") or "").strip()
        if artist and album and album.lower() not in (artist.lower(), (props.title or "").strip().lower()):
            subtitle = f"{artist} - {album}"
        else:
            subtitle = artist or album

        return {
            "title": props.title or "(tanpa judul)",
            "artist": subtitle,
            "status": int(info.playback_status),
            "pos": pos,
            "dur": dur,
            "thumb": self._thumb,
        }

    async def _fetch_thumb(self, props):
        try:
            ref = props.thumbnail
            if ref is None:
                return None
            stream = await ref.open_read_async()
            if stream is None or stream.size == 0:
                return None
            buf = Buffer(int(stream.size))
            await stream.read_async(buf, int(stream.size), InputStreamOptions.NONE)
            reader = DataReader.from_buffer(buf)
            n = reader.unconsumed_buffer_length
            if n == 0:
                return None
            # read_bytes() di winsdk mengisi buffer yang diberikan dan
            # mengembalikan None — bukan sebaliknya.
            out = bytearray(n)
            reader.read_bytes(out)
            return bytes(out)
        except Exception:
            return None


# ------------------------------------------------------------------ privasi --
# Windows mencatat setiap pemakaian mikrofon/kamera di CapabilityAccessManager.
# Per aplikasi ada dua nilai QWORD: LastUsedTimeStart (kapan mulai dipakai) dan
# LastUsedTimeStop (kapan selesai). Selama perangkat MASIH dipakai,
# LastUsedTimeStop = 0 — itu penanda "sedang aktif" yang sama dipakai panel
# Settings > Privacy. Nama kuncinya = aplikasi yang memakainya.
_CONSENT_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion"
    r"\CapabilityAccessManager\ConsentStore"
)
_PRIVACY_DEVICES = (("mic", "microphone"), ("cam", "webcam"))

# Nama tampilan untuk aplikasi paket (MSIX/UWP). Kunci registry memakai
# PackageFamilyName, mis. "Microsoft.WindowsCamera_8wekyb3d8bbwe".
_PACKAGED_NAMES = {
    "microsoft.windowscamera": "Camera",
    "microsoft.screensketch": "Snipping Tool",
    "microsoft.windowssoundrecorder": "Sound Recorder",
    "microsoftteams": "Teams",
    "msteams": "Teams",
    "clipchamp.clipchamp": "Clipchamp",
    "microsoft.xboxgamingoverlay": "Xbox Game Bar",
    "microsoft.gamingapp": "Xbox",
    "microsoft.microsoftofficehub": "Office",
    "microsoft.zunemusic": "Media Player",
    "microsoft.windowscommunicationsapps": "Mail",
    "microsoft.skypeapp": "Skype",
    "microsoft.yourphone": "Phone Link",
    "microsoft.windowsstore": "Store",
    "windows.immersivecontrolpanel": "Settings",
    "starbyteapps.webcamcapture": "Webcam Capture",
    "ad2f1837.hpprintercontrol": "HP Printer",
}

# Nama tampilan untuk aplikasi biasa (kunci NonPackaged berupa path exe).
_EXE_NAMES = {
    "chrome": "Chrome",
    "msedge": "Edge",
    "firefox": "Firefox",
    "brave": "Brave",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
    "discord": "Discord",
    "zoom": "Zoom",
    "teams": "Teams",
    "ms-teams": "Teams",
    "obs64": "OBS",
    "obs32": "OBS",
    "obs": "OBS",
    "audacity": "Audacity",
    "python": "Python",
    "pythonw": "Python",
    "python3": "Python",
    "code": "VS Code",
    "spotify": "Spotify",
    "slack": "Slack",
    "webex": "Webex",
    "webexmta": "Webex",
    "skype": "Skype",
    "steam": "Steam",
    "vlc": "VLC",
    "noktah": "Noktah",
}


def _packaged_label(key_name):
    family = key_name.split("_")[0]
    return _PACKAGED_NAMES.get(family.lower()) or family.rsplit(".", 1)[-1]


def _exe_label(path):
    base = path.replace("/", "\\").rsplit("\\", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    label = _EXE_NAMES.get(stem.lower())
    if label:
        return label
    label = stem.replace("_", " ").strip()
    return label[:1].upper() + label[1:] if label else "Aplikasi"


# --- pemeriksaan proses: registry bisa menyimpan entri "hantu" ---
# Aplikasi yang mati mendadak (crash / task manager) kadang meninggalkan
# LastUsedTimeStop = 0 selamanya. Tanpa verifikasi, titiknya menyala terus.
_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _load_kernel32():
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        k32.Process32FirstW.restype = wintypes.BOOL
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        k32.Process32NextW.restype = wintypes.BOOL
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        return k32
    except Exception:  # pragma: no cover
        return None


_K32 = _load_kernel32()


def _image_pids():
    """{nama exe huruf kecil: [pid]} — sekali per pembacaan registry."""
    if _K32 is None:
        return None
    pids = {}
    snap = _K32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or int(snap) == -1:
        return None
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = _K32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            name = (entry.szExeFile or "").lower()
            pids.setdefault(name, []).append(int(entry.th32ProcessID))
            ok = _K32.Process32NextW(snap, ctypes.byref(entry))
    except Exception:
        return None
    finally:
        _K32.CloseHandle(snap)
    return pids


def _process_path(pid):
    """Path lengkap sebuah proses, atau None kalau tidak bisa dibaca."""
    if _K32 is None:
        return None
    handle = _K32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not _K32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value or None
    finally:
        _K32.CloseHandle(handle)


_EXE_CACHE = {}


def _path_exists(path):
    hit = _EXE_CACHE.get(path)
    if hit is None:
        try:
            hit = os.path.exists(path)
        except OSError:
            hit = False
        if len(_EXE_CACHE) > 512:
            _EXE_CACHE.clear()
        _EXE_CACHE[path] = hit
    return hit


def _exe_still_running(key_name, running):
    """Apakah exe di balik entri NonPackaged benar-benar masih hidup."""
    exe = key_name.replace("#", "\\")
    if not _path_exists(exe):
        return False
    if running is None:  # snapshot proses gagal: percayai registry
        return True
    pids = running.get(exe.rsplit("\\", 1)[-1].lower())
    if not pids:
        return False
    unreadable = False
    for pid in pids:
        path = _process_path(pid)
        if path is None:
            unreadable = True
            continue
        if os.path.normcase(path) == os.path.normcase(exe):
            return True
    # Proses berjalan sebagai admin / tak terbaca: percayai nama exe-nya
    return unreadable


def _in_use(parent, name):
    try:
        with winreg.OpenKey(parent, name) as sub:
            start = int(winreg.QueryValueEx(sub, "LastUsedTimeStart")[0])
            stop = int(winreg.QueryValueEx(sub, "LastUsedTimeStop")[0])
    except (OSError, ValueError, TypeError):
        return False
    return start > 0 and stop == 0


def _active_apps(device, running):
    root_path = _CONSENT_KEY + "\\" + device
    found = []
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, root_path)
    except OSError:
        return found
    try:
        for i in range(winreg.QueryInfoKey(root)[0]):
            try:
                child = winreg.EnumKey(root, i)
            except OSError:
                break
            if child.lower() == "nonpackaged":
                continue
            if not _in_use(root, child):
                continue
            if "#" in child or ":" in child:
                # Windows 10 lama menaruh path exe langsung di bawah kunci
                # perangkat, bukan di subkunci NonPackaged.
                if _exe_still_running(child, running):
                    found.append(_exe_label(child.replace("#", "\\")))
            else:
                found.append(_packaged_label(child))
    except OSError:
        pass
    finally:
        root.Close()

    try:
        packed = winreg.OpenKey(winreg.HKEY_CURRENT_USER, root_path + r"\NonPackaged")
    except OSError:
        return found
    try:
        for i in range(winreg.QueryInfoKey(packed)[0]):
            try:
                child = winreg.EnumKey(packed, i)
            except OSError:
                break
            if _in_use(packed, child) and _exe_still_running(child, running):
                found.append(_exe_label(child.replace("#", "\\")))
    except OSError:
        pass
    finally:
        packed.Close()
    return found


def read_privacy_state():
    """{"mic": [nama app], "cam": [nama app]} — kosong kalau tidak dipakai."""
    state = {"mic": [], "cam": []}
    if winreg is None:
        return state
    running = _image_pids()
    for key, device in _PRIVACY_DEVICES:
        try:
            state[key] = sorted(set(_active_apps(device, running)))
        except Exception:
            state[key] = []
    return state


class PrivacyWatcher(QObject):
    """Membaca pemakaian mic/kamera di thread sendiri, lapor saat berubah."""

    changed = Signal(dict)

    def __init__(self, interval=PRIVACY_POLL_SEC):
        super().__init__()
        self._interval = max(0.15, float(interval))
        self._enabled = True
        self._stop = threading.Event()
        self._last = None

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        if not self._enabled:
            self._publish({"mic": [], "cam": []})

    def _publish(self, state):
        signature = (tuple(state["mic"]), tuple(state["cam"]))
        if signature == self._last:
            return
        self._last = signature
        self.changed.emit(state)

    def _loop(self):
        while not self._stop.is_set():
            if self._enabled:
                try:
                    self._publish(read_privacy_state())
                except Exception:
                    pass
            self._stop.wait(self._interval)


# -------------------------------------------------------------------- daya --
# GetSystemPowerStatus sudah cukup untuk tahu persen, status colokan, dan
# apakah sedang mengisi — tanpa paket tambahan seperti psutil.
class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", wintypes.BYTE),
        ("BatteryFlag", wintypes.BYTE),
        ("BatteryLifePercent", wintypes.BYTE),
        ("SystemStatusFlag", wintypes.BYTE),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


def read_power_status():
    """{'percent', 'plugged', 'charging', 'present'} atau None kalau gagal."""
    try:
        status = _SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return None
    except Exception:
        return None
    flags = int(status.BatteryFlag)
    percent = int(status.BatteryLifePercent)
    if percent > 100:  # 255 = tidak diketahui
        percent = None
    return {
        "percent": percent,
        "plugged": int(status.ACLineStatus) == 1,
        "charging": bool(flags & 0x08),
        "present": percent is not None and not (flags & 0x80),
    }


# -------------------------------------------------------------------- notch --
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1


class ClickThroughFilter(QAbstractNativeEventFilter):
    """Area transparan di luar pil tidak boleh menangkap klik sama sekali."""

    def __init__(self, notch):
        super().__init__()
        self._notch = notch

    def nativeEventFilter(self, eventType, message):
        if eventType != b"windows_generic_MSG":
            return False, 0
        notch = self._notch
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message != WM_NCHITTEST:
                return False, 0
            if int(msg.hWnd or 0) != int(notch.winId()):
                return False, 0
            lparam = int(msg.lParam)
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            if not notch.inside_pill_screen(x, y):
                return True, HTTRANSPARENT
        except Exception:
            return False, 0
        return False, 0


class Notch(QWidget):
    """Pil musik dengan animasi pegas ala Dynamic Island iOS."""

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setWindowTitle("Noktah")

        # --- pegas animasi ---
        self._expand = Spring(0.0, k=170.0, c=22.0)    # ringkas <-> membesar
        self._eq = Spring(0.0, k=110.0, c=16.0)        # tinggi equalizer
        self._glow = Spring(0.0, k=90.0, c=15.0)       # glow saat diputar
        self._content = Spring(1.0, k=240.0, c=26.0)   # slide teks saat lagu ganti
        self._art_fade = Spring(1.0, k=220.0, c=24.0)  # fade-in sampul
        self._btn_hover = [Spring(0.0, k=260.0, c=26.0) for _ in range(4)]

        # --- data media ---
        self._media = {
            "title": "Paper Sky",
            "artist": "Lumen Coast - Summer Flows",
            "status": 0,
            "pos": 0.0,
            "dur": 0.0,
            "thumb": None,
            "ts": time.monotonic(),
        }
        self._pix = None
        self._pix_key = None
        self._pix_scaled = None
        self._pix_scaled_size = 0
        self._accent = QColor(ACCENT_FALLBACK)

        # --- status interaksi ---
        self._phase = 0.0
        self._hovered = False
        self._pressed_btn = None
        self._hover_btn = None
        self._press_kind = None
        self._press_global = None
        self._press_anchor = None
        self._dragging = False
        self._scrubbing = False
        self._scrub_pos = 0.0
        self._disp_pos = 0.0
        self._snap = None  # (dari, ke, t)

        # --- font ---
        family = "Segoe UI Variable Display"
        try:
            if family not in QFontDatabase.families():
                family = "Segoe UI"
        except Exception:
            family = "Segoe UI"
        self._font_family = family

        # --- posisi awal: menempel di tengah atas layar ---
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self._anchor = QPointF(screen.center().x(), screen.top())

        # jendela berukuran tetap: animasi cukup melukis ulang, tanpa resize
        self.setFixedSize(int(WIN_W), int(WIN_H))
        self._last_tick = time.perf_counter()

        # --- timer animasi ---
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(self._collapse_if_idle)

        self._peek_timer = QTimer(self)
        self._peek_timer.setSingleShot(True)
        self._peek_timer.timeout.connect(self._collapse_if_idle)

        self.bridge.updated.connect(self.on_update)

        # --- indikator mic/kamera ---
        self._privacy = {"mic": [], "cam": []}
        self._privacy_anim = Spring(0.0, k=300.0, c=26.0)
        self._settings = None
        self._privacy_on = True
        try:
            self._settings = QSettings("Noktah", "Noktah")
            self._privacy_on = bool(
                self._settings.value("indikator_privasi", True, type=bool)
            )
        except Exception:
            self._settings = None
        self._watch = PrivacyWatcher()
        self._watch.changed.connect(self.on_privacy)
        self._watch.set_enabled(self._privacy_on)
        self._watch.start()

        # --- baterai ---
        self._power = None
        self._pulse_t = 0.0        # sisa detik denyut (hijau saat charger / merah saat low)
        self._pulse_phase = 0.0
        self._warn_t = 0.0         # sisa detik teks "Baterai lemah"
        self._warn_low = False     # sudah diperingatkan pada siklus pengosongan ini
        self._power_timer = QTimer(self)
        self._power_timer.setInterval(BATTERY_POLL_MS)
        self._power_timer.timeout.connect(self._poll_power)
        self._power_timer.start()
        self._poll_power()

        # filter klik-tembus; disimpan di atribut supaya tidak di-GC
        self._hit_filter = ClickThroughFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._hit_filter)

        self._apply_geometry()

    # ----------------------------------------------------------- geometri ---
    def _pill_size(self):
        t = clamp(self._expand.value, -0.02, 1.03)
        return lerp(COLLAPSED_W, EXPANDED_W, t), lerp(COLLAPSED_H, EXPANDED_H, t)

    def _apply_geometry(self):
        """Pindahkan jendela (ukurannya tetap) agar pil tetap di anchor-nya."""
        x = int(round(self._anchor.x() - WIN_W / 2.0))
        y = int(round(self._anchor.y()))
        if self.x() != x or self.y() != y:
            self.move(x, y)

    def _pill_rect(self):
        w, h = self._pill_size()
        return QRectF((WIN_W - w) / 2.0, 0.0, w, h)

    def inside_pill_screen(self, px, py):
        """True kalau titik layar (piksel fisik) berada di dalam pil."""
        dpr = self.devicePixelRatioF() or 1.0
        m = self._metrics()
        local = QPointF(px / dpr - self.x(), py / dpr - self.y())
        return self._pill_path(m["pill"], m["radius"], m["ear_r"]).contains(local)

    def _metrics(self):
        """Satu sumber kebenaran untuk melukis dan untuk hit-test."""
        t = clamp(self._expand.value, 0.0, 1.0)
        pill = self._pill_rect()
        radius = min(pill.height() / 2.0, lerp(18.0, 34.0, t))
        ear_r = lerp(10.0, 18.0, t)

        # Sampul album: kiri-bawah header saat membesar
        art_size = lerp(24.0, 86.0, t)
        art = QRectF(
            pill.left() + lerp(14.0, 24.0, t),
            lerp(pill.center().y() - art_size / 2.0, pill.top() + 54.0, t),
            art_size,
            art_size,
        )

        # Baris atas (header): kiri = cincin + tanggal/jam, tengah = dots, kanan = equalizer
        header_cy = pill.top() + 23.0

        eq_w, eq_h = 25.0, 18.0
        collapsed_eq_x = pill.center().x() - eq_w / 2.0 + 9.0
        eq_x = lerp(collapsed_eq_x, pill.right() - 26.0 - eq_w, t)
        eq_y = lerp(pill.center().y() - eq_h / 2.0, header_cy - eq_h / 2.0, t)
        eq = QRectF(eq_x, eq_y, eq_w, eq_h)

        # Dock kontrol kanan (prev, play/pause, next, chevron) dalam kapsul elegan
        dock_w, dock_h = 152.0, 56.0
        dock_rect = QRectF(
            pill.right() - 22.0 - dock_w,
            pill.top() + 69.0,
            dock_w,
            dock_h,
        )
        ctrl_cy = dock_rect.center().y()

        btn_rects = []
        centers = []
        btn_offsets = (22.0, 60.0, 98.0)
        for i, off in enumerate(btn_offsets):
            cx = dock_rect.left() + off
            cy = ctrl_cy
            centers.append(QPointF(cx, cy))
            r = 18.0 if i == 1 else 15.0
            btn_rects.append(QRectF(cx - r, cy - r, 2 * r, 2 * r))

        # Tombol chevron (>) di ujung kanan dock
        chev_center = QPointF(dock_rect.right() - 21.0, ctrl_cy)
        chev_rect = QRectF(chev_center.x() - 13.0, chev_center.y() - 13.0, 26.0, 26.0)
        centers.append(chev_center)
        btn_rects.append(chev_rect)

        # Kolom tengah: Judul, Artis, Bilah Progres, dan Waktu
        text_x = art.right() + lerp(12.0, 20.0, t)
        text_w = max(0.0, dock_rect.left() - 18.0 - text_x)
        title_rect = QRectF(text_x, pill.top() + 54.0, text_w, 24.0)
        artist_rect = QRectF(text_x, pill.top() + 78.0, text_w, 19.0)

        prog_cy = pill.top() + 113.0
        prog_rect = QRectF(text_x, prog_cy - 2.7, max(10.0, text_w), 5.4)
        time_left_rect = QRectF(text_x, prog_cy + 5.0, 64.0, 18.0)
        time_right_rect = QRectF(prog_rect.right() - 64.0, prog_cy + 5.0, 64.0, 18.0)

        dots_cy = header_cy

        return {
            "t": t,
            "pill": pill,
            "radius": radius,
            "ear_r": ear_r,
            "art": art,
            "eq": eq,
            "header_cy": header_cy,
            "dock": dock_rect,
            "title": title_rect,
            "artist": artist_rect,
            "time_left": time_left_rect,
            "time_right": time_right_rect,
            "progress": prog_rect,
            "progress_hit": prog_rect.adjusted(-6.0, -9.0, 6.0, 9.0),
            "buttons": btn_rects,
            "centers": centers,
            "chev_rect": chev_rect,
            "chev_center": chev_center,
            "dots_cy": dots_cy,
            "text_w": text_w,
            # area kecil yang berubah terus-menerus (untuk repaint parsial)
            "dirty_eq": eq.adjusted(-12.0, -10.0, 12.0, 10.0),
            "dirty_progress": QRectF(
                text_x - 8.0, prog_cy - 10.0, text_w + 16.0, 34.0
            ),
        }

    # ---------------------------------------------------------------- data ---
    def on_update(self, data):
        prev_key = (self._media.get("title"), self._media.get("artist"))
        new_key = (data.get("title"), data.get("artist"))
        data = dict(data)
        data["ts"] = time.monotonic()
        self._media = data

        if new_key != prev_key and data.get("title"):
            # lagu berganti: teks meluncur masuk, pil membesar sebentar
            self._content.jump(0.0)
            self._content.target = 1.0
            self._peek()

        thumb = data.get("thumb")
        if thumb is not None:
            if thumb is not self._pix_key:
                self._pix_key = thumb
                pix = QPixmap()
                if pix.loadFromData(thumb):
                    self._pix = pix
                    self._pix_scaled = None
                    self._accent = self._accent_from(pix)
                    self._art_fade.jump(0.0)
                    self._art_fade.target = 1.0
        elif self._pix_key is not None:
            self._pix_key = None
            self._pix = None
            self._pix_scaled = None

        if thumb is None and new_key != prev_key:
            # tanpa sampul: tetap beri aksen khas per lagu
            self._accent = self._accent_from_text(f"{new_key[0]}|{new_key[1]}")

        if data.get("status") != STATUS_PLAYING and not self._scrubbing:
            self._disp_pos = data.get("pos", 0.0)

    def _accent_from(self, pix):
        """Ambil warna paling 'hidup' dari sampul untuk aksen."""
        try:
            img = pix.toImage().scaled(
                24, 24, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
            )
            r = g = b = n = 0
            for y in range(img.height()):
                for x in range(img.width()):
                    c = img.pixelColor(x, y)
                    hue, sat, val, _ = c.getHsv()
                    if sat > 70 and val > 55:
                        r += c.red()
                        g += c.green()
                        b += c.blue()
                        n += 1
            if n == 0:
                return QColor(ACCENT_FALLBACK)
            color = QColor(r // n, g // n, b // n)
            hue, sat, val, _ = color.getHsv()
            if hue < 0:
                return QColor(ACCENT_FALLBACK)
            color.setHsv(hue, max(150, sat), max(195, val))
            return color
        except Exception:
            return QColor(ACCENT_FALLBACK)

    def _accent_from_text(self, text):
        """Aksen cadangan yang stabil per lagu kalau sampul tidak tersedia."""
        try:
            digest = hashlib.sha1(text.encode("utf-8", "ignore")).digest()
            hue = int(digest[0] / 255.0 * 359.0)
            return QColor.fromHsv(hue, 190, 238)
        except Exception:
            return QColor(ACCENT_FALLBACK)

    # -------------------------------------------------------------- privasi ---
    def on_privacy(self, state):
        mic = list(state.get("mic") or [])
        cam = list(state.get("cam") or [])
        if mic == self._privacy.get("mic") and cam == self._privacy.get("cam"):
            return
        self._privacy = {"mic": mic, "cam": cam}
        self._privacy_anim.target = 1.0 if (mic or cam) else 0.0
        self._wake()
        self.update()

    def _privacy_items(self):
        """Gabungkan per nama aplikasi: satu app bisa memakai mic & kamera."""
        items, by_name = [], {}
        for device, names in (
            ("mic", self._privacy.get("mic", [])),
            ("cam", self._privacy.get("cam", [])),
        ):
            for name in names:
                item = by_name.get(name)
                if item is None:
                    item = {"name": name, "devices": []}
                    by_name[name] = item
                    items.append(item)
                if device not in item["devices"]:
                    item["devices"].append(device)
        return items[:2]  # dua aplikasi sudah lebih dari cukup untuk satu badge

    def _save_privacy_flag(self):
        try:
            if self._settings is not None:
                self._settings.setValue("indikator_privasi", bool(self._privacy_on))
        except Exception:
            pass

    # ---------------------------------------------------------------- daya ---
    def _poll_power(self):
        power = read_power_status()
        if power != self._power:
            self.on_power(power)

    def on_power(self, power):
        prev = self._power
        self._power = power
        if not power or not power.get("present"):
            self._pulse_t = 0.0
            self._warn_t = 0.0
            self._warn_low = False
            self.update()
            return

        if prev and prev.get("present") and power["plugged"] and not prev["plugged"]:
            # charger baru dicolok: pil berdenyut hijau sebentar
            self._pulse_t = max(self._pulse_t, CHARGE_PULSE_SEC)
            self._pulse_phase = 0.0
            self._wake()

        percent = power["percent"]
        low = percent is not None and percent <= BATTERY_LOW
        if low and not power["plugged"]:
            if not self._warn_low:  # sekali per siklus pengosongan
                self._warn_low = True
                self._warn_t = BATTERY_WARN_SEC
                self._pulse_t = max(self._pulse_t, 3.0)
                self._pulse_phase = 0.0
                self._peek()        # panel membesar supaya peringatannya terlihat
                self._wake()
        elif power["plugged"] or not low:
            self._warn_low = False
        self.update()

    def _pulse_strength(self):
        if self._pulse_t <= 0.0:
            return 0.0
        return 0.5 + 0.5 * math.sin(self._pulse_phase)

    def _glow_state(self):
        """(warna, kekuatan) pendaran pil: hijau saat charger, merah saat low."""
        power = self._power or {}
        if not power.get("present"):
            return None, 0.0
        pulse = self._pulse_strength()
        pulsing = self._pulse_t > 0.0
        if power.get("plugged"):
            return CHARGE_COLOR, (0.45 + 0.55 * pulse) if pulsing else 0.32
        if self._warn_low:
            return LOW_COLOR, (0.4 + 0.6 * pulse) if pulsing else 0.0
        return None, 0.0

    def _advance_power(self, dt):
        """Jalankan denyut; True kalau animasi masih berjalan."""
        pulsing = False
        if self._pulse_t > 0.0:
            self._pulse_phase += dt * 5.4
            self._pulse_t = max(0.0, self._pulse_t - dt)
            pulsing = self._pulse_t > 0.0
            if not pulsing:
                self.update()  # sisa glow statis, tidak perlu 20 fps lagi
        if self._warn_t > 0.0:
            self._warn_t = max(0.0, self._warn_t - dt)
            if self._warn_t == 0.0:
                self.update()  # badge kembali ke tanggal & jam
        return pulsing

    # ------------------------------------------------------------- animasi ---
    def _all_springs(self):
        return [
            self._expand,
            self._eq,
            self._glow,
            self._content,
            self._art_fade,
            self._privacy_anim,
            *self._btn_hover,
        ]

    def _wake(self):
        """Mulai animasi seketika tanpa menunggu interval idle yang panjang."""
        if self._timer.interval() != 16:
            self._timer.setInterval(16)
            self._timer.start()

    def _tick(self):
        now = time.perf_counter()
        # dt nyata (dibatasi) supaya kecepatan animasi tetap sama walau
        # satu-dua frame terlewat.
        dt = clamp(now - self._last_tick, 0.001, 1.0 / 30.0)
        self._last_tick = now

        playing = self._media.get("status") == STATUS_PLAYING

        self._eq.target = 1.0 if playing else 0.0
        self._glow.target = 1.0 if playing else 0.0

        spring_moving = False
        for spring in self._all_springs():
            if not spring.settled():
                spring.step(dt)
                spring_moving = True

        eq_live = playing or self._eq.value > 0.02
        if eq_live:
            self._phase += dt * (3.6 + 4.2 * self._eq.value)

        progress_live = self._advance_progress(dt)
        snap_moving = self._advance_snap(dt)
        pulsing = self._advance_power(dt)

        if spring_moving or snap_moving:
            # bentuk pil berubah -> lukis ulang seluruhnya
            self.update()
            interval = 16
        elif eq_live or progress_live:
            # cuma equalizer/progres yang bergerak -> repaint kotak kecilnya
            m = self._metrics()
            self.update(m["dirty_eq"].toAlignedRect())
            if m["t"] > 0.45:
                self.update(m["dirty_progress"].toAlignedRect())
            interval = 16
        elif pulsing:
            # denyut baterai: 20 fps cukup untuk napas yang halus
            self.update()
            interval = 50
        else:
            interval = 100
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)

    def _advance_progress(self, dt):
        if self._scrubbing:
            target = self._scrub_pos
        else:
            playing = self._media.get("status") == STATUS_PLAYING
            base = self._media.get("pos", 0.0)
            if playing:
                base += time.monotonic() - self._media.get("ts", time.monotonic())
            dur = self._media.get("dur", 0.0)
            if dur > 0:
                base = min(base, dur)
            target = base

        diff = target - self._disp_pos
        if abs(diff) > 2.5:
            self._disp_pos = target
            return True
        if abs(diff) < 0.001:
            return False
        self._disp_pos += diff * min(1.0, dt * 9.0)
        return True

    def _advance_snap(self, dt):
        if not self._snap:
            return False
        start, end, t = self._snap
        t = min(1.0, t + dt * 3.4)
        ease = 1.0 - (1.0 - t) ** 3
        self._anchor = QPointF(
            lerp(start.x(), end.x(), ease), lerp(start.y(), end.y(), ease)
        )
        self._apply_geometry()
        self._snap = None if t >= 1.0 else (start, end, t)
        return True

    # ----------------------------------------------------------- interaksi ---
    def enterEvent(self, event):
        self._hovered = True
        self._collapse_timer.stop()
        self._expand.target = 1.0
        self._wake()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._press_global = None
        self._hover_btn = None
        for spring in self._btn_hover:
            spring.target = 0.0
        if not self._dragging:
            self._collapse_timer.start(420)
        super().leaveEvent(event)

    def _collapse_if_idle(self):
        if not self._hovered and not self._dragging and not self._scrubbing:
            self._expand.target = 0.0
            self._wake()

    def _peek(self):
        """Saat lagu berganti, pil membesar sebentar seperti notifikasi iOS."""
        if self._hovered or self._dragging:
            return
        self._expand.target = 1.0
        self._wake()
        self._peek_timer.start(2400)

    def _hit(self, pos, m):
        t = clamp(self._expand.value, 0.0, 1.0)
        if t > 0.45:
            for i, rect in enumerate(m["buttons"]):
                if rect.contains(pos):
                    return ("btn", i)
            if m["progress_hit"].contains(pos) and self._media.get("dur", 0.0) > 0:
                return ("prog", 0)
        return ("body", None)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        if not self._pill_rect().contains(event.position()):
            event.ignore()
            return

        self._snap = None
        self._peek_timer.stop()
        self._press_global = event.globalPosition()
        self._press_anchor = QPointF(self._anchor)
        self._dragging = False
        self.setFocus(Qt.MouseFocusReason)
        self._wake()

        m = self._metrics()
        kind, index = self._hit(event.position(), m)
        self._press_kind = kind
        self._pressed_btn = index if kind == "btn" else None

        if kind == "prog":
            self._scrubbing = True
            self._update_scrub(event.position(), m)
        self.update()
        event.accept()

    def mouseMoveEvent(self, event):
        m = self._metrics()
        kind, index = self._hit(event.position(), m)

        if self._press_global is not None and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition() - self._press_global
            if not self._dragging and delta.manhattanLength() > 4:
                self._dragging = True
                self._expand.target = 1.0
                self.setCursor(Qt.ClosedHandCursor)
            if self._dragging:
                self._anchor = QPointF(
                    self._press_anchor.x() + delta.x(),
                    self._press_anchor.y() + delta.y(),
                )
                self._apply_geometry()
                event.accept()
                return

        if self._scrubbing:
            self._update_scrub(event.position(), m)

        hover = index if kind == "btn" else None
        if hover != self._hover_btn:
            self._hover_btn = hover
            for i, spring in enumerate(self._btn_hover):
                spring.target = 1.0 if i == hover else 0.0
        if kind in ("btn", "prog"):
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        self.update()

    def _update_scrub(self, pos, m):
        track = m["progress"]
        dur = self._media.get("dur", 0.0)
        if dur <= 0 or track.width() <= 0:
            return
        frac = clamp((pos.x() - track.left()) / track.width(), 0.0, 1.0)
        self._scrub_pos = frac * dur
        self._disp_pos = self._scrub_pos

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            event.ignore()
            return

        m = self._metrics()
        kind, index = self._hit(event.position(), m)

        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)
            self._snap_to_top()

        elif self._scrubbing:
            self._scrubbing = False
            if self._media.get("dur", 0.0) > 0:
                self.bridge.enqueue(("seek", self._scrub_pos))
                self._media["pos"] = self._scrub_pos
                self._media["ts"] = time.monotonic()

        elif self._pressed_btn is not None:
            if kind == "btn" and index == self._pressed_btn:
                if index < 3:
                    self.bridge.enqueue(("prev", "toggle", "next")[index])
                else:
                    self.bridge.enqueue("next")

        elif self._press_kind == "body":
            if clamp(self._expand.value, 0.0, 1.0) < 0.5:
                self.bridge.enqueue("toggle")

        self._press_global = None
        self._press_kind = None
        self._pressed_btn = None
        self.update()
        event.accept()

    def _snap_to_top(self, center=False):
        """Selalu menempel lagi ke tepi atas layar; posisi x bebas."""
        screen = QGuiApplication.screenAt(self._anchor.toPoint())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        w, _ = self._pill_size()
        if center:
            x = geo.center().x()
        else:
            x = clamp(
                self._anchor.x(), geo.left() + w / 2.0, geo.right() - w / 2.0
            )
        target = QPointF(x, geo.top())
        if (
            abs(self._anchor.x() - x) > 0.5
            or abs(self._anchor.y() - target.y()) > 0.5
        ):
            self._snap = (QPointF(self._anchor), target, 0.0)
            self._wake()

    def contextMenuEvent(self, event):
        self._collapse_timer.stop()
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#231B17; color:#FAF3EB; border:1px solid #4A382E;"
            " border-radius:10px; padding:6px;}"
            "QMenu::item{padding:6px 22px; border-radius:6px;}"
            "QMenu::item:selected{background:#3A2C25;}"
        )
        act_privacy = menu.addAction("Indikator mic/kamera")
        act_privacy.setCheckable(True)
        act_privacy.setChecked(self._privacy_on)
        menu.addSeparator()
        act_quit = menu.addAction("Keluar")
        act_top = menu.addAction("Tempel ke atas (tengah)")
        chosen = menu.exec(event.globalPos())
        if chosen == act_quit:
            QApplication.quit()
        elif chosen == act_top:
            self._snap_to_top(center=True)
            self._wake()
        elif chosen == act_privacy:
            self._privacy_on = act_privacy.isChecked()
            self._watch.set_enabled(self._privacy_on)
            self._save_privacy_flag()
            self._wake()
            self.update()
        elif not self._hovered:
            self._collapse_timer.start(300)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            QApplication.quit()
        elif key == Qt.Key_Space:
            self.bridge.enqueue("toggle")
        elif key == Qt.Key_Left:
            self.bridge.enqueue("prev")
        elif key == Qt.Key_Right:
            self.bridge.enqueue("next")
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------ melukis ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        m = self._metrics()
        self._paint_shell(painter, m["pill"], m["radius"], m["ear_r"])
        self._paint_header(painter, m)
        self._paint_dots(painter, m)
        self._paint_privacy(painter, m)
        self._paint_art(painter, m)
        self._paint_equalizer(painter, m)
        self._paint_text(painter, m)
        self._paint_progress(painter, m)
        self._paint_controls(painter, m)
        painter.end()

    def _paint_shell(self, p, pill, radius, ear_r):
        glow = clamp(self._glow.value)
        p.setPen(Qt.NoPen)

        # Bayangan hangat lembut di bawah & samping notch
        for i in range(8, 0, -1):
            k = i / 8.0
            grow = 1.4 + 13.0 * k
            alpha = int(28 * (1.0 - k) ** 1.8)
            p.setBrush(QColor(14, 9, 6, alpha))
            shadow = pill.adjusted(-grow, 0.0, grow, grow * 1.3)
            p.drawPath(self._pill_path(shadow, radius + grow, ear_r))

        # Pendaran hangat champagne/bronze saat musik berputar
        if glow > 0.02:
            for i in range(4, 0, -1):
                grow = i * 2.5
                alpha = int(14 * glow * (1.0 - i / 5.0))
                if alpha <= 0:
                    continue
                p.setBrush(QColor(222, 174, 126, alpha))
                shadow = pill.adjusted(-grow, 0.0, grow, grow)
                p.drawPath(self._pill_path(shadow, radius + grow, ear_r))

        # Pendaran hijau saat charger dicolok (berdenyut 4 detik, lalu menetap
        # tipis), atau merah saat baterai lemah.
        tint, strength = self._glow_state()
        if tint is not None and strength > 0.02:
            for i in range(4, 0, -1):
                grow = i * 3.0
                alpha = int(16 * strength * (1.0 - i / 5.0))
                if alpha <= 0:
                    continue
                p.setBrush(QColor(tint.red(), tint.green(), tint.blue(), alpha))
                p.drawPath(
                    self._pill_path(
                        pill.adjusted(-grow, 0.0, grow, grow), radius + grow, ear_r
                    )
                )

        # Badan notch: gradasi coklat espresso / dark mocha elegan minimalis
        body = QLinearGradient(pill.topLeft(), pill.bottomLeft())
        body.setColorAt(0.0, QColor(48, 36, 30, 252))   # Roasted Espresso
        body.setColorAt(0.52, QColor(36, 27, 22, 254))  # Deep Mocha
        body.setColorAt(1.0, QColor(26, 19, 16, 255))   # Dark Walnut
        p.setBrush(body)
        shell_path = self._pill_path(pill, radius, ear_r)
        p.drawPath(shell_path)

        # Kilau halus hangat di bagian atas
        sheen = QLinearGradient(
            pill.topLeft(), QPointF(pill.left(), pill.top() + pill.height() * 0.55)
        )
        sheen.setColorAt(0.0, QColor(255, 232, 210, 22))
        sheen.setColorAt(1.0, QColor(255, 232, 210, 0))
        p.setBrush(sheen)
        p.drawPath(shell_path)

        # Garis tepi bronze/latte tipis nan elegan
        border_col = QColor(230, 196, 165, int(36 + 22 * glow))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(border_col, 1.0))
        p.drawPath(
            self._pill_path(pill.adjusted(0.5, 0.0, -0.5, -0.5), radius - 0.5, ear_r)
        )

    def _paint_header(self, p, m):
        alpha = smoothstep(0.42, 0.84, m["t"])
        if alpha <= 0.02:
            return

        pill = m["pill"]
        cy = m["header_cy"]

        p.save()
        p.setClipPath(self._pill_path(pill, m["radius"], m["ear_r"]))
        p.setOpacity(alpha)

        now = datetime.now()
        date_str = now.strftime("%a %d %b %Y")
        time_str = now.strftime("%H:%M")

        power = self._power or {}
        show_batt = bool(power.get("present"))
        percent = power.get("percent")
        warning = show_batt and self._warn_t > 0.0 and not power.get("plugged")

        date_font = QFont(self._font_family)
        date_font.setPixelSize(12)
        date_font.setWeight(QFont.Medium)
        fm_date = QFontMetrics(date_font)

        time_font = QFont(self._font_family)
        time_font.setPixelSize(12)
        time_font.setWeight(QFont.Bold)
        fm_time = QFontMetrics(time_font)

        # Saat baterai lemah, badge menampilkan peringatan menggantikan tanggal
        if warning:
            head_str = f"Baterai lemah {percent}%"
            head_font = time_font
        else:
            head_str = date_str
            head_font = date_font
        w_head = QFontMetrics(head_font).horizontalAdvance(head_str)
        w_time = 0 if warning else fm_time.horizontalAdvance(time_str)
        w_space = 0 if warning else 7

        icon_w = 23.0 if show_batt else 0.0
        icon_gap = 9.0 if show_batt else 0.0

        # Badge kiri atas: ikon baterai + tanggal (atau peringatan) + jam
        badge_x = pill.left() + 24.0
        content_w = icon_w + icon_gap + w_head + (w_space + w_time if w_time else 0)
        badge_rect = QRectF(badge_x - 8.0, cy - 12.5, content_w + 16.0, 25.0)
        if warning:
            p.setPen(QPen(QColor(255, 106, 92, 70), 1.0))
            p.setBrush(QColor(255, 82, 70, 20))
        else:
            p.setPen(QPen(QColor(235, 205, 175, 22), 1.0))
            p.setBrush(QColor(255, 238, 220, 12))
        p.drawRoundedRect(badge_rect, 12.5, 12.5)

        if show_batt:
            self._paint_battery(
                p, badge_x, cy, power, self._pulse_strength() if self._pulse_t > 0 else 0.0
            )

        text_x = badge_x + icon_w + icon_gap
        text_h = 20.0
        p.setPen(
            QColor(255, 132, 120, 250)
            if warning
            else QColor(208, 190, 175, 245)
        )
        p.setFont(head_font)
        p.drawText(
            QRectF(text_x, cy - text_h / 2.0, w_head + 4, text_h),
            Qt.AlignLeft | Qt.AlignVCenter,
            head_str,
        )

        if w_time:
            p.setPen(QColor(250, 243, 235, 252))
            p.setFont(time_font)
            p.drawText(
                QRectF(text_x + w_head + w_space, cy - text_h / 2.0, w_time + 4, text_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                time_str,
            )

        # Garis pemisah tipis antara bar status atas dan dek utama
        div_y = pill.top() + 41.5
        div_grad = QLinearGradient(pill.left() + 24.0, div_y, pill.right() - 24.0, div_y)
        div_grad.setColorAt(0.0, QColor(235, 205, 175, 10))
        div_grad.setColorAt(0.5, QColor(235, 205, 175, 34))
        div_grad.setColorAt(1.0, QColor(235, 205, 175, 10))
        p.setPen(QPen(div_grad, 1.0))
        p.drawLine(QPointF(pill.left() + 24.0, div_y), QPointF(pill.right() - 24.0, div_y))

        p.restore()

    def _paint_battery(self, p, x, cy, power, pulse=0.0):
        """Ikon baterai sungguhan: badan + terminal + isi + petir saat mengisi."""
        percent = power.get("percent")
        plugged = bool(power.get("plugged"))
        if plugged:
            color = CHARGE_COLOR
        elif percent is not None and percent <= BATTERY_LOW:
            color = LOW_COLOR
        elif percent is not None and percent <= 30:
            color = MID_COLOR
        else:
            color = BATT_LEVEL_COLOR

        h = 12.0
        body = QRectF(x, cy - h / 2.0, 20.0, h)
        nub = QRectF(body.right() + 0.5, cy - 2.2, 2.5, 4.4)

        # Halo lembut saat berdenyut
        if pulse > 0.02:
            halo = QColor(color)
            halo.setAlpha(int(62 * pulse))
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawRoundedRect(body.adjusted(-3.2, -3.2, 3.2, 3.2), 6.5, 6.5)

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 205), 1.3))
        p.drawRoundedRect(body, 3.2, 3.2)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color.red(), color.green(), color.blue(), 190))
        p.drawRoundedRect(nub, 1.0, 1.0)

        inner = body.adjusted(2.4, 2.4, -2.4, -2.4)
        frac = 1.0 if percent is None else clamp(percent / 100.0)
        fill_w = inner.width() * frac
        if fill_w > 0.6:
            fill = QRectF(inner.left(), inner.top(), fill_w, inner.height())
            grad = QLinearGradient(fill.topLeft(), fill.bottomLeft())
            grad.setColorAt(
                0.0,
                QColor(
                    min(255, color.red() + 28),
                    min(255, color.green() + 28),
                    min(255, color.blue() + 28),
                    235,
                ),
            )
            grad.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 225))
            p.setBrush(grad)
            p.drawRoundedRect(fill, 1.4, 1.4)

        if plugged:
            # Petir terang: tetap terbaca di atas isi baterai (hijau) maupun di
            # area kosong saat baterai masih rendah.
            cx, cyy = body.center().x(), cy
            bolt = QPolygonF(
                [
                    QPointF(cx + 1.7, cyy - 4.6),
                    QPointF(cx - 2.6, cyy + 0.4),
                    QPointF(cx - 0.3, cyy + 0.4),
                    QPointF(cx - 1.3, cyy + 4.6),
                    QPointF(cx + 2.8, cyy - 0.6),
                    QPointF(cx + 0.5, cyy - 0.6),
                ]
            )
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 247, 238, 246))
            p.drawPolygon(bolt)

    def _paint_art(self, p, m):
        rect = m["art"]
        radius = lerp(7.0, 18.0, m["t"])
        path = self._rounded_path(rect, radius)

        p.save()
        # Bayangan halus di bawah sampul album saat membesar
        if m["t"] > 0.3:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(12, 7, 5, int(75 * m["t"])))
            p.drawRoundedRect(rect.adjusted(-1.0, 2.0, 1.0, 4.0), radius + 1.0, radius + 1.0)

        p.setClipPath(path)
        p.setOpacity(clamp(self._art_fade.value))

        if self._pix is not None and not self._pix.isNull():
            size = max(1, int(round(rect.width())))
            if self._pix_scaled is None or self._pix_scaled_size != size:
                self._pix_scaled = self._pix.scaled(
                    size,
                    size,
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )
                self._pix_scaled_size = size
            scaled = self._pix_scaled
            p.drawPixmap(
                int(rect.left() - (scaled.width() - rect.width()) / 2),
                int(rect.top() - (scaled.height() - rect.height()) / 2),
                scaled,
            )
        else:
            # Sampul default bertema hangat minimalis (latte & piringan espresso-emas)
            bg = QLinearGradient(rect.topLeft(), rect.bottomRight())
            bg.setColorAt(0.0, QColor(242, 228, 212))
            bg.setColorAt(1.0, QColor(218, 195, 172))
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRect(rect)

            stripe_h = max(2.0, rect.height() / 14.0)
            p.setBrush(QColor(198, 170, 144, 145))
            y = rect.top() + stripe_h * 0.6
            while y < rect.bottom():
                p.drawRect(QRectF(rect.left(), y, rect.width(), stripe_h * 0.38))
                y += stripe_h

            disc_cx = rect.left() + rect.width() * 0.36
            disc_cy = rect.top() + rect.height() * 0.56
            outer_r = rect.width() * 0.29
            inner_r = rect.width() * 0.19

            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(142, 96, 62), max(1.5, rect.width() * 0.032)))
            p.drawEllipse(QPointF(disc_cx, disc_cy), outer_r, outer_r)

            p.setPen(Qt.NoPen)
            p.setBrush(QColor(96, 62, 42))
            p.drawEllipse(QPointF(disc_cx, disc_cy), inner_r, inner_r)

            diag_pen = QPen(QColor(255, 248, 240, 225), max(1.4, rect.width() * 0.025))
            p.setPen(diag_pen)
            p.drawLine(
                QPointF(rect.left() + rect.width() * 0.68, rect.top()),
                QPointF(rect.left() + rect.width() * 0.22, rect.bottom()),
            )
        p.restore()

        p.setOpacity(1.0)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(240, 212, 185, 48), 1.0))
        p.drawPath(path)

    def _paint_equalizer(self, p, m):
        rect = m["eq"]
        amp = clamp(self._eq.value)
        bars = 5
        bar_w = 2.6
        gap = 3.1
        total = bars * bar_w + (bars - 1) * gap
        x0 = rect.center().x() - total / 2.0
        cy = rect.center().y()

        idle_heights = (12.5, 5.6, 5.6, 9.4, 5.6)

        p.save()
        p.setClipPath(self._pill_path(m["pill"], m["radius"], m["ear_r"]))

        # Kapsul tipis pembungkus visualizer saat notch membesar
        if m["t"] > 0.45:
            cap_alpha = smoothstep(0.45, 0.85, m["t"])
            cap_rect = rect.adjusted(-8.0, -3.5, 8.0, 3.5)
            p.setPen(QPen(QColor(235, 205, 175, int(24 * cap_alpha)), 1.0))
            p.setBrush(QColor(255, 238, 220, int(12 * cap_alpha)))
            p.drawRoundedRect(cap_rect, cap_rect.height() / 2.0, cap_rect.height() / 2.0)

        p.setPen(Qt.NoPen)
        grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
        grad.setColorAt(0.0, QColor(250, 242, 232, 252))
        grad.setColorAt(1.0, QColor(222, 182, 142, 245))
        p.setBrush(grad)
        for i in range(bars):
            wave = abs(math.sin(self._phase + i * 0.85))
            live_h = 4.0 + 11.0 * (0.25 + 0.75 * wave)
            height = lerp(idle_heights[i], live_h, amp)
            bar = QRectF(x0 + i * (bar_w + gap), cy - height / 2.0, bar_w, height)
            p.drawRoundedRect(bar, bar_w / 2.0, bar_w / 2.0)
        p.restore()

    def _paint_text(self, p, m):
        alpha = smoothstep(0.46, 0.86, m["t"]) * clamp(self._content.value)
        if alpha <= 0.02:
            return

        dy = (1.0 - clamp(self._content.value)) * 8.0
        title_rect = m["title"].translated(0, dy)
        artist_rect = m["artist"].translated(0, dy)
        width = m["text_w"]
        if width <= 4:
            return

        p.save()
        p.setClipPath(self._pill_path(m["pill"], m["radius"], m["ear_r"]))
        p.setOpacity(alpha)

        title_font = QFont(self._font_family)
        title_font.setPixelSize(16)
        title_font.setWeight(QFont.Bold)
        p.setFont(title_font)
        p.setPen(QColor(250, 243, 235, 252))  # Warm Ivory
        title = str(self._media.get("title") or "")
        elided = QFontMetrics(title_font).elidedText(title, Qt.ElideRight, int(width))
        p.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, elided)

        artist_font = QFont(self._font_family)
        artist_font.setPixelSize(12)
        artist_font.setWeight(QFont.Medium)
        p.setFont(artist_font)
        fm = QFontMetrics(artist_font)

        artist = str(self._media.get("artist") or "")
        p.setPen(QColor(184, 161, 144, 240))  # Warm Latte Taupe
        p.drawText(
            artist_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            fm.elidedText(artist, Qt.ElideRight, int(width)),
        )

        p.restore()

    def _paint_progress(self, p, m):
        alpha = smoothstep(0.52, 0.90, m["t"])
        if alpha <= 0.02:
            return

        dur = self._media.get("dur", 0.0)
        pos = clamp(self._disp_pos, 0.0, dur) if dur > 0 else 0.0
        rem = max(0.0, dur - pos)

        track = m["progress"]
        p.save()
        p.setClipPath(self._pill_path(m["pill"], m["radius"], m["ear_r"]))
        p.setOpacity(alpha)

        # Bilah progres di kolom tengah dengan gradasi champagne-gold ke ivory
        p.setPen(Qt.NoPen)
        r = track.height() / 2.0
        p.setBrush(QColor(74, 57, 48, 235))
        p.drawRoundedRect(track, r, r)

        if dur > 0:
            frac = clamp(pos / dur, 0.0, 1.0)
            fill_w = max(track.height(), track.width() * frac)
            fill = QRectF(track.left(), track.top(), fill_w, track.height())
            grad = QLinearGradient(fill.left(), 0, fill.right(), 0)
            grad.setColorAt(0.0, QColor(214, 164, 116, 255))
            grad.setColorAt(1.0, QColor(250, 240, 228, 255))
            p.setBrush(grad)
            p.drawRoundedRect(fill, r, r)

        # Waktu berjalan (kiri bawah bar) & sisa waktu (kanan bawah bar)
        time_font = QFont(self._font_family)
        time_font.setPixelSize(11)
        time_font.setWeight(QFont.Medium)
        p.setFont(time_font)
        p.setPen(QColor(196, 174, 156, 235))
        p.drawText(m["time_left"], Qt.AlignLeft | Qt.AlignVCenter, fmt_time(pos))
        p.drawText(m["time_right"], Qt.AlignRight | Qt.AlignVCenter, f"-{fmt_time(rem)}")

        p.restore()

    def _paint_controls(self, p, m):
        alpha = smoothstep(0.56, 0.94, m["t"])
        if alpha <= 0.02:
            return

        playing = self._media.get("status") == STATUS_PLAYING
        is_demo = (
            self._pix is None
            and self._media.get("title") == "Paper Sky"
            and self._media.get("status") == 0
        )
        show_pause = playing or is_demo

        p.save()
        p.setClipPath(self._pill_path(m["pill"], m["radius"], m["ear_r"]))
        p.setOpacity(alpha)

        # Kapsul dock kontrol di sisi kanan
        dock = m["dock"]
        p.setPen(QPen(QColor(235, 205, 175, 28), 1.0))
        p.setBrush(QColor(255, 236, 218, 14))
        p.drawRoundedRect(dock, dock.height() / 2.0, dock.height() / 2.0)

        p.setPen(Qt.NoPen)
        for i in range(3):
            center = m["centers"][i]
            hover = clamp(self._btn_hover[i].value)
            pressed = self._pressed_btn == i
            scale = 0.92 if pressed else 1.0

            if i == 1:
                # Tombol utama Play/Pause dengan lingkaran Champagne Bronze elegan
                btn_r = 18.0 - 0.8 * hover
                btn_grad = QLinearGradient(
                    center.x(), center.y() - btn_r, center.x(), center.y() + btn_r
                )
                lift = int(16 * hover)
                btn_grad.setColorAt(0.0, QColor(min(255, 232 + lift), min(255, 192 + lift), min(255, 152 + lift)))
                btn_grad.setColorAt(1.0, QColor(min(255, 198 + lift), min(255, 148 + lift), min(255, 104 + lift)))
                p.setBrush(btn_grad)
                p.drawEllipse(center, btn_r, btn_r)
                # Ikon espresso gelap di atas tombol bronze
                p.setBrush(QColor(30, 21, 17, 252))
                if show_pause:
                    self._icon_pause(p, center, scale)
                else:
                    self._icon_play(p, center, scale)
            else:
                if hover > 0.02:
                    radius = 14.5 - 0.8 * hover
                    p.setBrush(
                        QColor(250, 235, 220, int((24 if not pressed else 40) * hover))
                    )
                    p.drawEllipse(center, radius, radius)
                icon_alpha = 255 if pressed else int(225 + 30 * hover)
                p.setBrush(QColor(250, 243, 235, icon_alpha))
                if i == 0:
                    self._icon_prev(p, center, scale)
                else:
                    self._icon_next(p, center, scale)

        # Tombol bulat mocha dengan chevron (>) di sebelah kanan dock
        chev_center = m["chev_center"]
        chev_hover = clamp(self._btn_hover[3].value)
        chev_pressed = self._pressed_btn == 3
        r_col = int(76 + 20 * chev_hover + (10 if chev_pressed else 0))
        g_col = int(58 + 16 * chev_hover + (8 if chev_pressed else 0))
        b_col = int(49 + 14 * chev_hover + (6 if chev_pressed else 0))
        p.setPen(QPen(QColor(235, 205, 175, 32), 1.0))
        p.setBrush(QColor(r_col, g_col, b_col, 255))
        p.drawEllipse(chev_center, 12.5, 12.5)
        self._icon_chevron(p, chev_center, 0.92 if chev_pressed else 1.0)

        p.restore()

    def _paint_dots(self, p, m):
        alpha = smoothstep(0.50, 0.88, m["t"])
        if alpha <= 0.02:
            return

        cy = m["dots_cy"]
        pill_w = 16.0
        dot_d = 4.0
        gap = 5.5
        total_w = pill_w + 4 * gap + 4 * dot_d
        # Diposisikan di bagian atas-tengah (di antara badge tanggal & visualizer)
        x = m["pill"].center().x() - total_w / 2.0 + 36.0

        p.save()
        p.setClipPath(self._pill_path(m["pill"], m["radius"], m["ear_r"]))
        p.setOpacity(alpha)
        p.setPen(Qt.NoPen)

        # Indikator halaman aktif (pil champagne ivory)
        p.setBrush(QColor(236, 204, 172, 245))
        p.drawRoundedRect(QRectF(x, cy - dot_d / 2.0, pill_w, dot_d), dot_d / 2.0, dot_d / 2.0)
        x += pill_w + gap

        # 4 titik indikator mocha lembut
        p.setBrush(QColor(124, 98, 82, 225))
        for _ in range(4):
            p.drawEllipse(QRectF(x, cy - dot_d / 2.0, dot_d, dot_d))
            x += dot_d + gap

        p.restore()

    def _paint_privacy(self, p, m):
        """Titik oranye/hijau: titik saja saat ringkas, titik + nama saat besar."""
        anim = clamp(self._privacy_anim.value)
        if anim <= 0.02:
            return
        items = self._privacy_items()
        if not items:
            return

        devices = []
        for item in items:
            for device in item["devices"]:
                if device not in devices:
                    devices.append(device)
        color_of = {"mic": MIC_COLOR, "cam": CAM_COLOR}

        pill = m["pill"]
        p.save()
        p.setClipPath(self._pill_path(pill, m["radius"], m["ear_r"]))
        p.setOpacity(anim)

        # Ringkas: titik di ujung kanan pil, selalu kelihatan
        dot_alpha = 1.0 - smoothstep(0.16, 0.48, m["t"])
        if dot_alpha > 0.02:
            diameter = 7.0 * (0.7 + 0.3 * anim)
            gap = 5.0
            total = len(devices) * diameter + (len(devices) - 1) * gap
            x = pill.right() - 12.0 - total
            cy = pill.center().y()
            for device in devices:
                self._privacy_dot(
                    p, QPointF(x + diameter / 2.0, cy), diameter, color_of[device], dot_alpha
                )
                x += diameter + gap

        # Membesar: kapsul kecil berisi titik + nama aplikasi
        cap_alpha = smoothstep(0.5, 0.88, m["t"])
        if cap_alpha > 0.02:
            self._paint_privacy_capsule(p, m, items, color_of, cap_alpha)

        p.restore()

    def _paint_privacy_capsule(self, p, m, items, color_of, alpha):
        pill = m["pill"]
        cy = m["header_cy"]
        h = 22.0

        font = QFont(self._font_family)
        font.setPixelSize(10)
        font.setWeight(QFont.DemiBold)
        fm = QFontMetrics(font)

        pad_l = 9.0
        pad_r = 9.0
        dot_d = 7.0
        dot_gap = 3.0
        name_gap = 5.0
        item_gap = 11.0

        # Kanan: tepat di kiri kapsul equalizer (posisinya ikut beranimasi).
        # Kiri: tepat di kanan titik-titik halaman, supaya tidak bertumpuk.
        right_edge = m["eq"].left() - 8.0 - 9.0
        left_edge = pill.center().x() + 71.0
        avail = right_edge - left_edge
        if avail < 48.0:  # pil belum cukup lebar (di tengah animasi)
            return

        def assemble(labels):
            widths = []
            for item, label in zip(items, labels):
                w = len(item["devices"]) * dot_d + (len(item["devices"]) - 1) * dot_gap
                if label:
                    w += name_gap + fm.horizontalAdvance(label)
                widths.append(w)
            total = pad_l + pad_r + sum(widths) + (len(items) - 1) * item_gap
            return widths, total

        fixed = pad_l + pad_r + sum(
            len(item["devices"]) * dot_d + (len(item["devices"]) - 1) * dot_gap
            + name_gap
            for item in items
        ) + (len(items) - 1) * item_gap
        budget = max(0.0, avail - fixed) / max(1, len(items))

        labels = []
        for item in items:
            label = item["name"]
            if budget < 26.0:
                label = ""
            elif fm.horizontalAdvance(label) > budget:
                label = fm.elidedText(label, Qt.ElideRight, int(budget))
            labels.append(label)

        widths, content_w = assemble(labels)
        if content_w > avail:
            # belum ada ruang (di tengah animasi): tampilkan titiknya dulu
            labels = [""] * len(items)
            widths, content_w = assemble(labels)
        if content_w <= 0:
            return

        tint = color_of[items[0]["devices"][0]]
        x = right_edge - content_w
        cap_rect = QRectF(x, cy - h / 2.0, content_w, h)
        p.setPen(QPen(QColor(tint.red(), tint.green(), tint.blue(), int(48 * alpha)), 1.0))
        p.setBrush(QColor(tint.red(), tint.green(), tint.blue(), int(18 * alpha)))
        p.drawRoundedRect(cap_rect, h / 2.0, h / 2.0)

        p.setFont(font)
        cx = x + pad_l
        for index, (item, label) in enumerate(zip(items, labels)):
            if index:
                cx += item_gap
            for j, device in enumerate(item["devices"]):
                if j:
                    cx += dot_gap
                self._privacy_dot(
                    p, QPointF(cx + dot_d / 2.0, cy), dot_d, color_of[device], alpha
                )
                cx += dot_d
            if label:
                cx += name_gap
                text_w = fm.horizontalAdvance(label)
                p.setPen(QColor(250, 243, 235, int(240 * alpha)))
                p.drawText(
                    QRectF(cx, cy - h / 2.0, text_w + 2.0, h),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    label,
                )
                cx += text_w

    @staticmethod
    def _privacy_dot(p, center, diameter, color, alpha=1.0):
        """Titik dengan halo tipis supaya terbaca di panel gelap."""
        r = max(0.5, diameter / 2.0)
        p.setPen(Qt.NoPen)
        halo = QColor(color)
        halo.setAlpha(int(72 * alpha))
        p.setBrush(halo)
        p.drawEllipse(center, r * 1.8, r * 1.8)
        core = QColor(color)
        core.setAlpha(int(255 * alpha))
        p.setBrush(core)
        p.drawEllipse(center, r, r)

    @staticmethod
    def _icon_prev(p, c, scale=1.0):
        """Dua segitiga menghadap kiri (<<) persis seperti pada gambar."""
        h = 5.6 * scale
        w = 6.6 * scale
        gap = 1.4 * scale
        cx, cy = c.x(), c.y()
        # Segitiga kiri
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(cx - gap / 2.0, cy - h),
                    QPointF(cx - gap / 2.0, cy + h),
                    QPointF(cx - gap / 2.0 - w, cy),
                ]
            )
        )
        # Segitiga kanan
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(cx + gap / 2.0 + w, cy - h),
                    QPointF(cx + gap / 2.0 + w, cy + h),
                    QPointF(cx + gap / 2.0, cy),
                ]
            )
        )

    @staticmethod
    def _icon_next(p, c, scale=1.0):
        """Dua segitiga menghadap kanan (>>) persis seperti pada gambar."""
        h = 5.6 * scale
        w = 6.6 * scale
        gap = 1.4 * scale
        cx, cy = c.x(), c.y()
        # Segitiga kiri
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(cx - gap / 2.0 - w, cy - h),
                    QPointF(cx - gap / 2.0 - w, cy + h),
                    QPointF(cx - gap / 2.0, cy),
                ]
            )
        )
        # Segitiga kanan
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(cx + gap / 2.0, cy - h),
                    QPointF(cx + gap / 2.0, cy + h),
                    QPointF(cx + gap / 2.0 + w, cy),
                ]
            )
        )

    @staticmethod
    def _icon_play(p, c, scale=1.0):
        s = 6.4 * scale
        cx, cy = c.x() + 0.8, c.y()
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(cx - s + 1.0, cy - s),
                    QPointF(cx - s + 1.0, cy + s),
                    QPointF(cx + s + 1.0, cy),
                ]
            )
        )

    @staticmethod
    def _icon_pause(p, c, scale=1.0):
        s = 6.4 * scale
        cx, cy = c.x(), c.y()
        p.drawRoundedRect(QRectF(cx - 4.8, cy - s, 3.2, 2 * s), 1.2, 1.2)
        p.drawRoundedRect(QRectF(cx + 1.6, cy - s, 3.2, 2 * s), 1.2, 1.2)

    @staticmethod
    def _icon_chevron(p, c, scale=1.0):
        s = 4.0 * scale
        cx, cy = c.x() + 0.5, c.y()
        pen = QPen(QColor(250, 243, 235, 245), 2.0 * scale)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.save()
        p.setBrush(Qt.NoBrush)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(cx - s * 0.55, cy - s)
        path.lineTo(cx + s * 0.55, cy)
        path.lineTo(cx - s * 0.55, cy + s)
        p.drawPath(path)
        p.restore()

    @staticmethod
    def _rounded_path(rect, radius):
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    @staticmethod
    def _pill_path(rect, radius, ear_r=0.0):
        """Panel yang menempel ke tepi atas layar: lekuk telinga atas & bawah bulat."""
        r = max(0.0, min(radius, rect.width() / 2.0, rect.height()))
        er = max(0.0, min(ear_r, rect.height() - r))
        path = QPainterPath()
        path.moveTo(rect.left() - er, rect.top())
        path.lineTo(rect.right() + er, rect.top())
        if er > 0.0:
            path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + er)
        path.lineTo(rect.right(), rect.bottom() - r)
        path.quadTo(rect.right(), rect.bottom(), rect.right() - r, rect.bottom())
        path.lineTo(rect.left() + r, rect.bottom())
        path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - r)
        if er > 0.0:
            path.lineTo(rect.left(), rect.top() + er)
            path.quadTo(rect.left(), rect.top(), rect.left() - er, rect.top())
        path.closeSubpath()
        return path

    def sizeHint(self):
        return self.geometry().size()


def main():
    app = QApplication(sys.argv)
    bridge = MediaBridge()
    notch = Notch(bridge)
    bridge.start()
    notch.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
