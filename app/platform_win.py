"""
Windows platform katmanı — Win32 (ctypes) ile fare/dokunmatik olayları (SendInput),
ekran listesi (EnumDisplayMonitors + QueryDisplayConfig ile yerleşik panel tespiti),
ana ekran değiştirme (ChangeDisplaySettingsEx) ve uyku engelleme (SetThreadExecutionState).

Koordinatlar fiziksel pikseldir: süreç Per-Monitor DPI Aware yapılır, böylece
mss ekran yakalama ile fare koordinatları birebir örtüşür.
"""

import ctypes
import time
from ctypes import wintypes
from typing import Optional

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _enable_dpi_awareness():
    """Ölçekli (125%/150%) ekranlarda koordinat kaymasını önlemek için DPI farkındalığını açar."""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


# ---------------------------------------------------------------- SendInput
ULONG_PTR = ctypes.c_size_t


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


# ------------------------------------------------------------ Monitör bilgisi
class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32),
    ]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
)


# ------------------------------------------------------- QueryDisplayConfig
class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [("adapterId", _LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("statusFlags", ctypes.c_uint32)]


class _RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", ctypes.c_uint32), ("Denominator", ctypes.c_uint32)]


class _PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", _LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
        ("outputTechnology", ctypes.c_uint32), ("rotation", ctypes.c_uint32), ("scaling", ctypes.c_uint32),
        ("refreshRate", _RATIONAL), ("scanLineOrdering", ctypes.c_uint32), ("targetAvailable", wintypes.BOOL),
        ("statusFlags", ctypes.c_uint32),
    ]


class _PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", _PATH_SOURCE_INFO), ("targetInfo", _PATH_TARGET_INFO), ("flags", ctypes.c_uint32)]


class _MODE_INFO(ctypes.Structure):
    _fields_ = [("infoType", ctypes.c_uint32), ("id", ctypes.c_uint32), ("adapterId", _LUID),
                ("data", ctypes.c_byte * 48)]


class _DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapterId", _LUID), ("id", ctypes.c_uint32)]


class _SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", _DEVICE_INFO_HEADER), ("viewGdiDeviceName", wintypes.WCHAR * 32)]


# ---------------------------------------------------------------- DEVMODEW
class _DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD), ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD), ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD),
    ]


class WinController:
    """Win32 fare, ekran listesi/ana ekran ve uyku engelleme denetleyicisi (MacController ile aynı arayüz)."""

    INPUT_MOUSE = 0
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_WHEEL = 0x0800
    MOUSEEVENTF_HWHEEL = 0x1000
    WHEEL_DELTA = 120

    MONITORINFOF_PRIMARY = 0x1
    QDC_ONLY_ACTIVE_PATHS = 0x2
    DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1
    # Yerleşik panel çıkış teknolojileri: INTERNAL, DISPLAYPORT_EMBEDDED, UDI_EMBEDDED
    INTERNAL_OUTPUTS = {0x80000000, 11, 13}

    ENUM_CURRENT_SETTINGS = -1
    DM_POSITION = 0x00000020
    CDS_UPDATEREGISTRY = 0x00000001
    CDS_SET_PRIMARY = 0x00000010
    CDS_NORESET = 0x10000000
    DISP_CHANGE_SUCCESSFUL = 0

    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002

    def __init__(self):
        _enable_dpi_awareness()
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, _MONITORENUMPROC, wintypes.LPARAM]
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFOEXW)]
        user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_DEVMODEW)]
        user32.ChangeDisplaySettingsExW.argtypes = [
            wintypes.LPCWSTR, ctypes.POINTER(_DEVMODEW), wintypes.HWND, wintypes.DWORD, ctypes.c_void_p
        ]
        user32.ChangeDisplaySettingsExW.restype = wintypes.LONG
        kernel32.SetThreadExecutionState.argtypes = [wintypes.DWORD]
        kernel32.SetThreadExecutionState.restype = wintypes.DWORD

        self._left_down = False
        self._right_down = False
        self._internal_names_cache: Optional[set[str]] = None
        self._internal_cache_time = 0.0

    # ------------------------------------------------------------ Ekranlar
    def _internal_display_names(self) -> set[str]:
        """Yerleşik (dizüstü) panele bağlı GDI ekran adlarını döndürür (ör. \\\\.\\DISPLAY1)."""
        now = time.monotonic()
        if self._internal_names_cache is not None and now - self._internal_cache_time < 5.0:
            return self._internal_names_cache
        names: set[str] = set()
        try:
            n_paths = ctypes.c_uint32(0)
            n_modes = ctypes.c_uint32(0)
            if user32.GetDisplayConfigBufferSizes(self.QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths), ctypes.byref(n_modes)) == 0:
                paths = (_PATH_INFO * n_paths.value)()
                modes = (_MODE_INFO * n_modes.value)()
                if user32.QueryDisplayConfig(
                    self.QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths), paths, ctypes.byref(n_modes), modes, None
                ) == 0:
                    for i in range(n_paths.value):
                        path = paths[i]
                        if path.targetInfo.outputTechnology not in self.INTERNAL_OUTPUTS:
                            continue
                        src = _SOURCE_DEVICE_NAME()
                        src.header.type = self.DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
                        src.header.size = ctypes.sizeof(_SOURCE_DEVICE_NAME)
                        src.header.adapterId = path.sourceInfo.adapterId
                        src.header.id = path.sourceInfo.id
                        if user32.DisplayConfigGetDeviceInfo(ctypes.byref(src.header)) == 0:
                            names.add(src.viewGdiDeviceName)
        except Exception:
            pass
        self._internal_names_cache = names
        self._internal_cache_time = now
        return names

    def get_all_displays(self) -> list[dict]:
        """Windows ekranlarını listeler (yerleşik dizüstü ekranı her zaman 1. sıradadır)."""
        internal = self._internal_display_names()
        items: list[dict] = []

        def _cb(hmon, _hdc, _rect, _lparam):
            info = _MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                r = info.rcMonitor
                items.append({
                    "id": info.szDevice,
                    "builtin": info.szDevice in internal,
                    "is_main": bool(info.dwFlags & self.MONITORINFOF_PRIMARY),
                    "left": int(r.left),
                    "top": int(r.top),
                    "width": int(r.right - r.left),
                    "height": int(r.bottom - r.top),
                })
            return True

        user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(_cb), 0)
        items.sort(key=lambda d: (0 if d["builtin"] else 1, 0 if d["is_main"] else 1, d["id"]))
        return items

    def get_display_bounds_by_index(self, index: int = 1) -> tuple:
        displays = self.get_all_displays()
        if displays:
            d = displays[max(0, min(len(displays) - 1, index - 1))]
            return (d["id"], d["left"], d["top"], d["width"], d["height"])
        w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        return ("primary", 0, 0, int(w), int(h))

    def set_main_display(self, target_id: str) -> bool:
        """Verilen ekranı Windows birincil ekranı yapar (görev çubuğu oraya taşınır).

        Birincil ekran (0,0) orijinindeki ekrandır; tüm ekranlar göreli yerleşimleri
        korunarak hedef ekran orijine gelecek şekilde kaydırılır.
        """
        displays = self.get_all_displays()
        target = next((d for d in displays if d["id"] == target_id), None)
        if target is None or target["is_main"]:
            return False
        dx, dy = target["left"], target["top"]
        ok = True
        # Önce birincil ekranı, sonra diğerlerini ayarla; tamamı en sonda tek seferde uygulanır.
        for d in sorted(displays, key=lambda d: 0 if d["id"] == target_id else 1):
            dm = _DEVMODEW()
            dm.dmSize = ctypes.sizeof(_DEVMODEW)
            if not user32.EnumDisplaySettingsW(d["id"], self.ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
                ok = False
                continue
            dm.dmPositionX = d["left"] - dx
            dm.dmPositionY = d["top"] - dy
            dm.dmFields = self.DM_POSITION
            flags = self.CDS_UPDATEREGISTRY | self.CDS_NORESET
            if d["id"] == target_id:
                flags |= self.CDS_SET_PRIMARY
            if user32.ChangeDisplaySettingsExW(d["id"], ctypes.byref(dm), None, flags, None) != self.DISP_CHANGE_SUCCESSFUL:
                ok = False
        user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
        return ok

    # ---------------------------------------------------------------- Fare
    def _send_mouse(self, flags: int, data: int = 0):
        inp = _INPUT(type=self.INPUT_MOUSE)
        inp.u.mi = _MOUSEINPUT(0, 0, ctypes.c_uint32(data).value, flags, 0, 0)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    def get_position(self) -> tuple[float, float]:
        pt = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return (0.0, 0.0)
        return (float(pt.x), float(pt.y))

    def move(self, x: float, y: float):
        user32.SetCursorPos(int(round(x)), int(round(y)))

    def move_rel(self, dx: float, dy: float):
        cx, cy = self.get_position()
        self.move(cx + dx, cy + dy)

    def down(self, x: Optional[float], y: Optional[float], right: bool = False):
        if x is not None and y is not None:
            self.move(x, y)
            time.sleep(0.012)
        if right:
            self._right_down = True
            self._send_mouse(self.MOUSEEVENTF_RIGHTDOWN)
        else:
            self._left_down = True
            self._send_mouse(self.MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.012)

    def up(self, x: Optional[float], y: Optional[float], right: bool = False):
        if x is not None and y is not None:
            self.move(x, y)
        if right:
            self._right_down = False
            self._send_mouse(self.MOUSEEVENTF_RIGHTUP)
        else:
            self._left_down = False
            self._send_mouse(self.MOUSEEVENTF_LEFTUP)

    def click(self, x: Optional[float], y: Optional[float], right: bool = False, count: int = 1):
        if x is not None and y is not None:
            self.move(x, y)
            time.sleep(0.010)
        down_f = self.MOUSEEVENTF_RIGHTDOWN if right else self.MOUSEEVENTF_LEFTDOWN
        up_f = self.MOUSEEVENTF_RIGHTUP if right else self.MOUSEEVENTF_LEFTUP
        for _ in range(max(1, min(3, count))):
            self._send_mouse(down_f)
            time.sleep(0.010)
            self._send_mouse(up_f)
            time.sleep(0.010)

    def scroll(self, dx: int, dy: int):
        # macOS ile aynı yön: dy>0 yukarı; yatayda macOS'ta pozitif sola, Windows'ta sağa kaydırır.
        if dy:
            self._send_mouse(self.MOUSEEVENTF_WHEEL, int(dy) * self.WHEEL_DELTA)
        if dx:
            self._send_mouse(self.MOUSEEVENTF_HWHEEL, -int(dx) * self.WHEEL_DELTA)

    # -------------------------------------------------------------- Sistem
    def is_accessibility_trusted(self, prompt: bool = False) -> bool:
        """Windows'ta ayrı bir erişilebilirlik izni yoktur."""
        return True

    def start_keep_awake(self):
        kernel32.SetThreadExecutionState(self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED | self.ES_DISPLAY_REQUIRED)

    def stop_keep_awake(self):
        kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)
