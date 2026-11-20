"""
macOS platform katmanı — CoreGraphics (ctypes) ile fare/dokunmatik olayları,
ekran listesi, ana ekran değiştirme, Erişilebilirlik izni ve uyku engelleme.
"""

import ctypes
import subprocess
import time
from typing import Optional


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("w", ctypes.c_double), ("h", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


class MacController:
    """Saf macOS CoreGraphics (CGEvent) fare, ekran listesi/ana ekran ve uyku engelleme denetleyicisi."""

    kCGHIDEventTap = 0
    kCGEventLeftMouseDown = 1
    kCGEventLeftMouseUp = 2
    kCGEventRightMouseDown = 3
    kCGEventRightMouseUp = 4
    kCGEventMouseMoved = 5
    kCGEventLeftMouseDragged = 6
    kCGEventRightMouseDragged = 7
    kCGMouseButtonLeft = 0
    kCGMouseButtonRight = 1
    kCGMouseEventNumber = 0
    kCGMouseEventClickState = 1
    kCGMouseEventDeltaX = 4
    kCGMouseEventDeltaY = 5
    kCGScrollEventUnitLine = 1

    def __init__(self):
        self.cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        self.cg.CGMainDisplayID.restype = ctypes.c_uint32
        self.cg.CGDisplayIsBuiltin.argtypes = [ctypes.c_uint32]
        self.cg.CGDisplayIsBuiltin.restype = ctypes.c_uint32
        self.cg.CGGetOnlineDisplayList.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)
        ]
        self.cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        self.cg.CGDisplayBounds.restype = _CGRect
        self.cg.CGEventCreate.argtypes = [ctypes.c_void_p]
        self.cg.CGEventCreate.restype = ctypes.c_void_p
        self.cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
        self.cg.CGEventGetLocation.restype = _CGPoint
        self.cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, _CGPoint, ctypes.c_uint32]
        self.cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        self.cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
        self.cg.CGEventCreateScrollWheelEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32
        ]
        self.cg.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p
        self.cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        self.cg.CFRelease.argtypes = [ctypes.c_void_p]
        self.cg.CGBeginDisplayConfiguration.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self.cg.CGBeginDisplayConfiguration.restype = ctypes.c_int32
        self.cg.CGConfigureDisplayOrigin.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32]
        self.cg.CGConfigureDisplayOrigin.restype = ctypes.c_int32
        self.cg.CGCompleteDisplayConfiguration.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.cg.CGCompleteDisplayConfiguration.restype = ctypes.c_int32
        self.cg.CGCancelDisplayConfiguration.argtypes = [ctypes.c_void_p]
        self.cg.CGCancelDisplayConfiguration.restype = ctypes.c_int32

        self._left_down = False
        self._right_down = False
        self._event_num = 1
        self._last_x = 0.0
        self._last_y = 0.0
        self._caffeinate_proc: Optional[subprocess.Popen] = None

    def get_all_displays(self) -> list[dict]:
        """macOS çevrimiçi ekranlarını listeler (Yerleşik Mac ekranı her zaman 1. sıradadır)."""
        ids = (ctypes.c_uint32 * 8)()
        cnt = ctypes.c_uint32(0)
        self.cg.CGGetOnlineDisplayList(8, ids, ctypes.byref(cnt))
        main_id = self.cg.CGMainDisplayID()
        items = []
        for i in range(cnt.value):
            did = int(ids[i])
            b = self.cg.CGDisplayBounds(did)
            items.append({
                "id": did,
                "builtin": bool(self.cg.CGDisplayIsBuiltin(did)),
                "is_main": did == main_id,
                "left": int(b.origin.x),
                "top": int(b.origin.y),
                "width": int(b.size.w),
                "height": int(b.size.h),
            })
        items.sort(key=lambda d: (0 if d["builtin"] else 1, 0 if d["is_main"] else 1, d["id"]))
        return items

    def set_main_display(self, target_id: int) -> bool:
        """Verilen ekranı macOS ana ekranı yapar (menü çubuğu + Dock oraya taşınır).

        macOS'ta ana ekran (0,0) orijinindeki ekrandır; tüm ekranlar göreli
        yerleşimleri korunarak hedef ekran orijine gelecek şekilde kaydırılır.
        """
        displays = self.get_all_displays()
        target = next((d for d in displays if d["id"] == target_id), None)
        if target is None or (target["left"] == 0 and target["top"] == 0):
            return False
        dx, dy = target["left"], target["top"]
        config = ctypes.c_void_p()
        if self.cg.CGBeginDisplayConfiguration(ctypes.byref(config)) != 0:
            return False
        for d in displays:
            if self.cg.CGConfigureDisplayOrigin(config, d["id"], d["left"] - dx, d["top"] - dy) != 0:
                self.cg.CGCancelDisplayConfiguration(config)
                return False
        kCGConfigurePermanently = 2
        return self.cg.CGCompleteDisplayConfiguration(config, kCGConfigurePermanently) == 0

    def get_display_bounds_by_index(self, index: int = 1) -> tuple[int, int, int, int, int]:
        displays = self.get_all_displays()
        if displays:
            d = displays[max(0, min(len(displays) - 1, index - 1))]
            return (d["id"], d["left"], d["top"], d["width"], d["height"])
        did = self.cg.CGMainDisplayID()
        b = self.cg.CGDisplayBounds(did)
        return (int(did), int(b.origin.x), int(b.origin.y), int(b.size.w), int(b.size.h))

    def get_position(self) -> tuple[float, float]:
        ev = self.cg.CGEventCreate(None)
        if not ev:
            return (0.0, 0.0)
        pt = self.cg.CGEventGetLocation(ev)
        self.cg.CFRelease(ev)
        return (float(pt.x), float(pt.y))

    def _post_mouse(
        self,
        ev_type: int,
        x: float,
        y: float,
        button: int = 0,
        click_state: int = 0,
        event_num: int = 0,
        dx: int = 0,
        dy: int = 0,
    ):
        ev = self.cg.CGEventCreateMouseEvent(None, ev_type, _CGPoint(x, y), button)
        if not ev:
            return
        if event_num > 0:
            self.cg.CGEventSetIntegerValueField(ev, self.kCGMouseEventNumber, event_num)
        if click_state > 0:
            self.cg.CGEventSetIntegerValueField(ev, self.kCGMouseEventClickState, click_state)
        if dx != 0:
            self.cg.CGEventSetIntegerValueField(ev, self.kCGMouseEventDeltaX, dx)
        if dy != 0:
            self.cg.CGEventSetIntegerValueField(ev, self.kCGMouseEventDeltaY, dy)
        self.cg.CGEventPost(self.kCGHIDEventTap, ev)
        self.cg.CFRelease(ev)
        self._last_x = x
        self._last_y = y

    def move(self, x: float, y: float):
        dx = int(round(x - self._last_x))
        dy = int(round(y - self._last_y))
        if self._left_down:
            self._post_mouse(
                self.kCGEventLeftMouseDragged, x, y, self.kCGMouseButtonLeft,
                event_num=self._event_num, dx=dx, dy=dy
            )
        elif self._right_down:
            self._post_mouse(
                self.kCGEventRightMouseDragged, x, y, self.kCGMouseButtonRight,
                event_num=self._event_num, dx=dx, dy=dy
            )
        else:
            self._post_mouse(self.kCGEventMouseMoved, x, y, self.kCGMouseButtonLeft, dx=dx, dy=dy)

    def move_rel(self, dx: float, dy: float):
        cx, cy = self.get_position()
        self.move(cx + dx, cy + dy)

    def down(self, x: Optional[float], y: Optional[float], right: bool = False):
        if x is None or y is None:
            x, y = self.get_position()
        else:
            self._post_mouse(self.kCGEventMouseMoved, x, y, self.kCGMouseButtonLeft)
            time.sleep(0.012)
        self._event_num += 1
        if right:
            self._right_down = True
            self._post_mouse(self.kCGEventRightMouseDown, x, y, self.kCGMouseButtonRight, 1, self._event_num)
        else:
            self._left_down = True
            self._post_mouse(self.kCGEventLeftMouseDown, x, y, self.kCGMouseButtonLeft, 1, self._event_num)
        time.sleep(0.012)

    def up(self, x: Optional[float], y: Optional[float], right: bool = False):
        if x is None or y is None:
            x, y = self.get_position()
        if right:
            self._right_down = False
            self._post_mouse(self.kCGEventRightMouseUp, x, y, self.kCGMouseButtonRight, 1, self._event_num)
        else:
            self._left_down = False
            self._post_mouse(self.kCGEventLeftMouseUp, x, y, self.kCGMouseButtonLeft, 1, self._event_num)

    def click(self, x: Optional[float], y: Optional[float], right: bool = False, count: int = 1):
        if x is None or y is None:
            x, y = self.get_position()
        self._post_mouse(self.kCGEventMouseMoved, x, y, self.kCGMouseButtonLeft)
        time.sleep(0.010)
        btn = self.kCGMouseButtonRight if right else self.kCGMouseButtonLeft
        down_ev = self.kCGEventRightMouseDown if right else self.kCGEventLeftMouseDown
        up_ev = self.kCGEventRightMouseUp if right else self.kCGEventLeftMouseUp
        self._event_num += 1
        for i in range(1, max(1, min(3, count)) + 1):
            self._post_mouse(down_ev, x, y, btn, i, self._event_num)
            time.sleep(0.010)
            self._post_mouse(up_ev, x, y, btn, i, self._event_num)

    def scroll(self, dx: int, dy: int):
        ev = self.cg.CGEventCreateScrollWheelEvent(None, self.kCGScrollEventUnitLine, 2, int(dy), int(dx))
        if ev:
            self.cg.CGEventPost(self.kCGHIDEventTap, ev)

    def is_accessibility_trusted(self, prompt: bool = False) -> bool:
        try:
            asvc = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
            if not prompt:
                asvc.AXIsProcessTrusted.restype = ctypes.c_bool
                return bool(asvc.AXIsProcessTrusted())

            cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            cf.CFDictionaryCreate.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
                ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p
            ]
            cf.CFDictionaryCreate.restype = ctypes.c_void_p
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            k_prompt = ctypes.c_void_p.in_dll(asvc, "kAXTrustedCheckOptionPrompt")
            k_true = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")
            opts = cf.CFDictionaryCreate(None, (ctypes.c_void_p * 1)(k_prompt), (ctypes.c_void_p * 1)(k_true), 1, None, None)
            asvc.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
            asvc.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
            trusted = bool(asvc.AXIsProcessTrustedWithOptions(opts))
            if opts:
                cf.CFRelease(opts)
            return trusted
        except Exception:
            return True

    def start_keep_awake(self):
        """Yayın sürerken ekranın/sistemin uyumasını engeller."""
        try:
            self._caffeinate_proc = subprocess.Popen(
                ["caffeinate", "-d", "-i"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            self._caffeinate_proc = None

    def stop_keep_awake(self):
        if self._caffeinate_proc:
            try:
                self._caffeinate_proc.terminate()
            except Exception:
                pass
            self._caffeinate_proc = None
