#!/usr/bin/env python3
"""
Ekran Yansıtıcı — Ekranı kırık Mac / Windows dizüstü için Android Tablet Ana Monitör Sunucusu
  • Tablet bağlıyken yerleşik ekran (tablet) ana ekrandır; tablet yokken harici monitör ana ekran olur
  • 60 FPS, düşük gecikmeli 4:2:0 JPEG + canlı fare imleci
  • Dokunmatik, sürükle-bırak ve klavye kontrolü (platform_mac.py / platform_win.py)
  • Otomatik USB ADB Köprüsü + Wi-Fi desteği
"""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
import warnings
from io import BytesIO
from pathlib import Path
from typing import Optional

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

try:
    # Windows'ta dosyaya yönlendirilen çıktı cp1252 olur; emojili loglar çökmesin diye UTF-8'e zorla
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
except Exception:
    pass

# Sanal ortam paketlerini sys.path'e ekle
for venv_candidate in (BASE_DIR / "venv", BASE_DIR.parent / "venv"):
    lib_dir = venv_candidate / "lib"
    if lib_dir.exists():
        for py_dir in lib_dir.iterdir():
            sp = py_dir / "site-packages"
            if sp.exists() and str(sp) not in sys.path:
                sys.path.insert(0, str(sp))

import aiohttp
from aiohttp import web
import mss
from PIL import Image, ImageDraw
from pynput.keyboard import Controller as KeyboardController, Key

from pin_auth import PinGuard, is_local_address
from usb_bridge import UsbAdbBridge

DEFAULT_PORT = 8080
PKT_JPEG = b"\x03"
AUTH_TIMEOUT_SECONDS = 120


from platform_layer import IS_MAC, IS_WINDOWS, PLATFORM_NAME, controller

try:
    keyboard = KeyboardController()
except Exception as e:
    keyboard = None
    print(f"⚠️  Klavye kontrolcüsü başlatılamadı: {e}")

SPECIAL_KEYS = {
    "Enter": Key.enter,
    "Return": Key.enter,
    "Backspace": Key.backspace,
    "Delete": Key.delete,
    "Tab": Key.tab,
    "Escape": Key.esc,
    "Space": Key.space,
    " ": Key.space,
    "ArrowUp": Key.up,
    "ArrowDown": Key.down,
    "ArrowLeft": Key.left,
    "ArrowRight": Key.right,
}

MODIFIER_KEYS = {
    # Windows'ta Cmd kısayolları (Cmd+C vb.) Ctrl karşılığına çevrilir
    "cmd": Key.ctrl if IS_WINDOWS else Key.cmd,
    "meta": Key.ctrl if IS_WINDOWS else Key.cmd,
    "ctrl": Key.ctrl,
    "alt": Key.alt,
    "shift": Key.shift,
}


def free_port(port: int):
    """Portu tutan eski süreçleri sonlandırır (yalnızca macOS; Windows'ta lsof yok)."""
    if not IS_MAC:
        return
    try:
        out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True, stderr=subprocess.DEVNULL).strip()
        if out:
            cur_pid = os.getpid()
            for pid_str in out.split():
                try:
                    p = int(pid_str)
                    if p != cur_pid:
                        os.kill(p, 9)
                except Exception:
                    pass
            time.sleep(0.3)
    except Exception:
        pass


def get_system_local_ip() -> str:
    for iface in (("en0", "en1", "en2", "en3", "en4") if IS_MAC else ()):
        try:
            out = subprocess.check_output(
                ["ipconfig", "getifaddr", iface], text=True, stderr=subprocess.DEVNULL
            ).strip()
            if out and not out.startswith("127."):
                return out
        except Exception:
            pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    finally:
        s.close()
    return "127.0.0.1"


class ClientSession:
    def __init__(self, ws: web.WebSocketResponse, client_id: str, ip: str):
        self.ws = ws
        self.client_id = client_id
        self.ip = ip
        self.protocol = 2
        self.busy = False


class StreamServer:
    def __init__(
        self,
        port: int = DEFAULT_PORT,
        preferred_monitor: int = 1,
        fps: int = 60,
        quality: int = 78,
        auto_main_display: bool = True,
        pin_guard: Optional[PinGuard] = None,
    ):
        self.port = port
        self.fps = fps
        self.quality = quality
        self.scale_factor = 1.0
        self.max_width = 1920
        self.running = True
        self.touch_enabled = True
        self.active_monitor_index = preferred_monitor

        self.device_name = socket.gethostname()
        self.local_ip = get_system_local_ip()
        self.capture_lock = threading.Lock()
        self.sct = mss.mss()
        self.sessions: dict[web.WebSocketResponse, ClientSession] = {}
        self._last_main_display_sig = self._get_active_bounds_tuple()
        self._last_perm_warn_time = 0.0
        self.auto_main_display = auto_main_display
        self._tablet_last_seen = 0.0

        self.pin_guard = pin_guard or PinGuard(enabled=False)
        self.usb_bridge = UsbAdbBridge(port=self.port, auto_open_browser=True)

    def _get_active_bounds_tuple(self):
        try:
            if controller:
                return controller.get_display_bounds_by_index(self.active_monitor_index)
        except Exception:
            pass
        return None


    def refresh_monitors(self):
        with self.capture_lock:
            try:
                self.sct.close()
                self.sct = mss.mss()
            except Exception:
                pass

    def list_monitors(self) -> list[dict]:
        if controller:
            displays = controller.get_all_displays()
            if displays:
                return [
                    {
                        "index": idx,
                        "label": "Yerleşik Ekran (Tablet)" if d["builtin"] else f"Harici Monitör {idx}",
                        "left": d["left"],
                        "top": d["top"],
                        "width": d["width"],
                        "height": d["height"],
                        "is_active": idx == self.active_monitor_index,
                    }
                    for idx, d in enumerate(displays, start=1)
                ]
        return []

    def _draw_cursor(self, img: Image.Image, mon_left: int, mon_top: int, mon_w: int, mon_h: int):
        if not controller or mon_w <= 0 or mon_h <= 0:
            return
        try:
            mx, my = controller.get_position()
            nx = (mx - mon_left) / mon_w
            ny = (my - mon_top) / mon_h
            if not (-0.02 <= nx <= 1.02 and -0.02 <= ny <= 1.02):
                return
            cx = int(max(0.0, min(1.0, nx)) * (img.width - 1))
            cy = int(max(0.0, min(1.0, ny)) * (img.height - 1))
            pts = [
                (cx, cy), (cx, cy + 22), (cx + 6, cy + 16), (cx + 10, cy + 25),
                (cx + 13, cy + 23), (cx + 9, cy + 14), (cx + 17, cy + 14),
            ]
            ImageDraw.Draw(img).polygon(pts, fill="#000000", outline="#FFFFFF")
        except Exception:
            pass

    def capture_jpeg_frame(self) -> Optional[bytes]:
        try:
            live_bounds = self._get_active_bounds_tuple()
            if live_bounds is not None and live_bounds != self._last_main_display_sig:
                self._last_main_display_sig = live_bounds
                print(f"🖥️  Ekran değişikliği algılandı (ID={live_bounds[0]}, {live_bounds[3]}x{live_bounds[4]})")

            with self.capture_lock:
                if live_bounds is not None and live_bounds[3] > 0 and live_bounds[4] > 0:
                    _, mon_left, mon_top, mon_w, mon_h = live_bounds
                    monitor = {"left": mon_left, "top": mon_top, "width": mon_w, "height": mon_h}
                else:
                    monitor = self.sct.monitors[1] if len(self.sct.monitors) > 1 else self.sct.monitors[0]
                    mon_left, mon_top, mon_w, mon_h = monitor["left"], monitor["top"], monitor["width"], monitor["height"]
                sct_img = self.sct.grab(monitor)

            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

            target_w = int(img.width * self.scale_factor)
            if target_w > self.max_width:
                ratio = self.max_width / img.width
                target_w = self.max_width
                target_h = int(img.height * ratio)
            else:
                target_h = int(img.height * self.scale_factor)

            if target_w < img.width - 4:
                img = img.resize((max(320, target_w), max(180, target_h)), Image.Resampling.BILINEAR)

            self._draw_cursor(img, mon_left, mon_top, mon_w, mon_h)

            buf = BytesIO()
            img.save(buf, format="JPEG", quality=self.quality, subsampling=2, optimize=False)
            return buf.getvalue()
        except Exception as e:
            self.refresh_monitors()
            now = time.time()
            if now - self._last_perm_warn_time > 10:
                self._last_perm_warn_time = now
                print(f"❌ Ekran yakalama hatası: {e}")
            return None

    async def _safe_close(self, ws: web.WebSocketResponse):
        try:
            await asyncio.wait_for(ws.close(), timeout=0.3)
        except Exception:
            pass

    async def _send_frame_to_session(self, session: ClientSession, pkt: bytes) -> bool:
        if session.busy:
            return True
        session.busy = True
        try:
            await asyncio.wait_for(session.ws.send_bytes(pkt), timeout=0.6)
            return True
        except Exception:
            return False
        finally:
            session.busy = False

    async def jpeg_broadcaster(self):
        while self.running:
            if not self.sessions:
                await asyncio.sleep(0.05)
                continue

            start = time.monotonic()
            try:
                frame = await asyncio.wait_for(asyncio.to_thread(self.capture_jpeg_frame), timeout=2.0)
            except asyncio.TimeoutError:
                await asyncio.to_thread(self.refresh_monitors)
                continue
            except Exception:
                await asyncio.sleep(0.05)
                continue

            if frame:
                v2_pkt = PKT_JPEG + frame
                clients_snapshot = list(self.sessions.values())
                results = await asyncio.gather(
                    *(self._send_frame_to_session(s, v2_pkt) for s in clients_snapshot),
                    return_exceptions=True,
                )
                for s, ok in zip(clients_snapshot, results):
                    if ok is not True:
                        self.sessions.pop(s.ws, None)
                        asyncio.create_task(self._safe_close(s.ws))

            elapsed = time.monotonic() - start
            await asyncio.sleep(max(0.002, (1.0 / self.fps) - elapsed))

    def _apply_main_display(self, tablet_connected: bool):
        """Tablet bağlıysa yerleşik ekranı, değilse ilk harici monitörü ana ekran yapar."""
        if not controller:
            return
        displays = controller.get_all_displays()
        builtin = next((d for d in displays if d["builtin"]), None)
        external = next((d for d in displays if not d["builtin"]), None)
        if builtin is None or external is None:
            return
        target = builtin if tablet_connected else external
        if target["is_main"]:
            return
        if controller.set_main_display(target["id"]):
            self.refresh_monitors()
            print(f"🖥️  Ana ekran → {'Tablet (Yerleşik Ekran)' if tablet_connected else 'Harici Monitör'}")

    async def main_display_watcher(self):
        """Tablet bağlantısını izler; kısa kopmalarda ana ekranın zıplamaması için 4 sn tolerans tanır."""
        grace = 4.0
        # Açılışta USB köprüsü tableti bulana kadar ~10 sn karar verme (gereksiz ekran zıplamasını önler)
        self._tablet_last_seen = time.monotonic() + 6.0
        while self.running:
            now = time.monotonic()
            if self.sessions or self.usb_bridge.get_devices():
                self._tablet_last_seen = now
            tablet_connected = now - self._tablet_last_seen < grace
            try:
                await asyncio.to_thread(self._apply_main_display, tablet_connected)
            except Exception as e:
                print(f"⚠️  Ana ekran değiştirilemedi: {e}")
            await asyncio.sleep(1.0)

    def handle_input_event(self, data: dict):
        event_type = data.get("type")
        if not event_type:
            return

        if event_type == "key_text":
            text = data.get("text", "")
            if text and keyboard:
                try:
                    keyboard.type(text)
                except Exception:
                    pass
            return

        if event_type == "key_press" and keyboard:
            key_name = data.get("key", "")
            modifiers = data.get("modifiers", [])
            mod_objs = [MODIFIER_KEYS[m.lower()] for m in modifiers if m.lower() in MODIFIER_KEYS]
            target_key = SPECIAL_KEYS.get(key_name) or (key_name if len(key_name) == 1 else None)
            if target_key is not None:
                try:
                    for m in mod_objs:
                        keyboard.press(m)
                    keyboard.tap(target_key)
                    for m in reversed(mod_objs):
                        keyboard.release(m)
                except Exception:
                    pass
            return

        if not self.touch_enabled or not controller:
            return

        if event_type == "mouse_move_rel":
            controller.move_rel(float(data.get("dx", 0)), float(data.get("dy", 0)))
            return

        if event_type == "scroll":
            controller.scroll(int(round(float(data.get("dx", 0)))), int(round(float(data.get("dy", 0)))))
            return

        target_x = None
        target_y = None
        if "x" in data and "y" in data:
            b = self._get_active_bounds_tuple()
            if b is not None and b[3] > 0 and b[4] > 0:
                target_x = b[1] + float(data["x"]) * b[3]
                target_y = b[2] + float(data["y"]) * b[4]

        is_right = data.get("button") == "right"
        if event_type == "mouse_move" and target_x is not None:
            controller.move(target_x, target_y)
        elif event_type == "mouse_down":
            controller.down(target_x, target_y, right=is_right)
        elif event_type == "mouse_up":
            controller.up(target_x, target_y, right=is_right)
        elif event_type == "click":
            controller.click(target_x, target_y, right=is_right, count=int(data.get("count", 1)))

    async def websocket_handler(self, request: web.Request):
        ws = web.WebSocketResponse(heartbeat=15)
        await ws.prepare(request)

        client_ip = request.remote or "unknown"
        client_id = f"{client_ip}:{id(ws)}"
        is_usb = is_local_address(client_ip)

        if self.pin_guard.requires_auth(client_ip) and not await self._authenticate(ws, client_ip):
            await self._safe_close(ws)
            return ws

        session = ClientSession(ws, client_id, client_ip)
        self.sessions[ws] = session
        print(f"📱  Tablet bağlandı ({'USB' if is_usb else 'Wi-Fi'}): {client_id}")

        init_msg = {
            "type": "init",
            "device_name": self.device_name,
            "monitors": self.list_monitors(),
            "active_monitor": self.active_monitor_index,
            "ax_trusted": controller.is_accessibility_trusted() if controller else False,
            "connection_mode": "usb" if is_usb else "wifi",
        }
        # PIN yalnızca USB'ye bağlı tablete gösterilir: ekran kırıkken PIN'i görmenin yolu budur
        if is_usb and self.pin_guard.enabled:
            init_msg["wifi_pin"] = self.pin_guard.pin
        await ws.send_json(init_msg)

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        msg_type = data.get("type")
                        if msg_type == "set_touch_enabled":
                            self.touch_enabled = bool(data.get("enabled", True))
                        elif msg_type == "select_monitor":
                            idx = int(data.get("index", 1))
                            if 1 <= idx <= max(1, len(self.list_monitors())):
                                self.active_monitor_index = idx
                        elif msg_type == "refresh_monitors":
                            self.refresh_monitors()
                        elif msg_type not in ("hello", "client_resolution"):
                            self.handle_input_event(data)
                    except Exception:
                        pass
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
        finally:
            self.sessions.pop(ws, None)
            print(f"🔌  Tablet ayrıldı: {client_id}")

        return ws

    async def _authenticate(self, ws: web.WebSocketResponse, client_ip: str) -> bool:
        """Wi-Fi istemcisinden PIN veya kayıtlı jeton bekler. Doğrulanana kadar görüntü/girdi yoktur."""
        guard = self.pin_guard
        await ws.send_json({"type": "auth_required", "locked_for": guard.locked_for(client_ip)})
        deadline = time.monotonic() + AUTH_TIMEOUT_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                msg = await ws.receive(timeout=remaining)
            except asyncio.TimeoutError:
                return False
            if msg.type != aiohttp.WSMsgType.TEXT:
                if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING,
                                aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    return False
                continue
            try:
                data = json.loads(msg.data)
            except Exception:
                continue
            if data.get("type") != "auth":
                continue

            if "token" in data:
                ok, locked, left = guard.check_token(data.get("token")), guard.locked_for(client_ip), None
            else:
                ok, locked, left = guard.try_pin(client_ip, data.get("pin"))

            if ok:
                await ws.send_json({"type": "auth_ok", "token": guard.token()})
                return True
            reply = {"type": "auth_failed", "locked_for": locked, "via": "token" if "token" in data else "pin"}
            if left is not None:
                reply["attempts_left"] = left
            await ws.send_json(reply)

    async def api_info(self, request: web.Request):
        if self.pin_guard.requires_auth(request.remote) and not self.pin_guard.check_token(
            request.headers.get("X-Ekran-Token") or request.query.get("token")
        ):
            return web.json_response({"error": "PIN gerekli"}, status=401)
        return web.json_response(
            {
                "service": "ekran-yansitici",
                "name": self.device_name,
                "ip": get_system_local_ip(),
                "port": self.port,
                "monitors": self.list_monitors(),
                "clients_count": len(self.sessions),
                "usb_devices": self.usb_bridge.get_devices(),
            },
            headers={"Access-Control-Allow-Origin": "*"},
        )

    async def index_handler(self, request: web.Request):
        index_file = WEB_DIR / "index.html"
        if index_file.exists():
            return web.FileResponse(index_file, headers={"Cache-Control": "no-store, must-revalidate"})
        return web.Response(text="Web arayüzü bulunamadı", status=404)

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        self.usb_bridge.start()

        app = web.Application()
        app.router.add_get("/", self.index_handler)
        app.router.add_get("/ws", self.websocket_handler)
        app.router.add_get("/api/info", self.api_info)
        if WEB_DIR.exists():
            app.router.add_static("/", path=str(WEB_DIR), show_index=False)

        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())

        for attempt in range(3):
            try:
                free_port(self.port)
                site = web.TCPSite(runner, "0.0.0.0", self.port, reuse_address=True)
                loop.run_until_complete(site.start())
                break
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(0.5)

        self.local_ip = get_system_local_ip()
        ax_ok = controller.is_accessibility_trusted(prompt=True) if controller else False
        print("=" * 60)
        print(f"🖥️   EKRAN YANSITICI — {PLATFORM_NAME.upper()} → ANDROID TABLET MONİTÖR")
        print("=" * 60)
        print(f"🔌  USB Kablo (Otomatik) : http://127.0.0.1:{self.port}  (ADB: {'Hazır' if self.usb_bridge.is_available else 'Yok'})")
        print(f"📡  Wi-Fi (Kablosuz)     : http://{self.local_ip}:{self.port}")
        print(f"📺  Aktif Ekran          : Monitör {self.active_monitor_index} (Yerleşik Ekran)")
        print(f"🖱️  Erişilebilirlik İzni : {'✅ Açık (Dokunmatik aktif!)' if ax_ok else '⚠️ KAPALI'}")
        if self.pin_guard.enabled:
            print(f"🔒  Wi-Fi PIN            : {self.pin_guard.pin}  (USB'de sorulmaz)")
        else:
            print("🔓  Wi-Fi PIN            : KAPALI (ağdaki herkes bağlanabilir!)")
        print("=" * 60)

        if controller:
            controller.start_keep_awake()

        broadcaster_task = loop.create_task(self.jpeg_broadcaster())
        display_task = loop.create_task(self.main_display_watcher()) if self.auto_main_display else None
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            broadcaster_task.cancel()
            if display_task:
                display_task.cancel()
            if controller:
                controller.stop_keep_awake()
            self.usb_bridge.stop()
            loop.run_until_complete(runner.cleanup())
            loop.close()


def main():
    parser = argparse.ArgumentParser(description="Ekran Yansıtıcı Sunucusu (macOS / Windows)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--monitor", type=int, default=1)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--quality", type=int, default=78)
    parser.add_argument("--no-auto-main", action="store_true", help="Ana ekranı tablete göre otomatik değiştirme")
    parser.add_argument("--pin", help="Wi-Fi PIN'ini bu değerle değiştir (kaydedilmez; EKRAN_PIN ile de verilebilir)")
    parser.add_argument("--reset-pin", action="store_true", help="Yeni rastgele PIN üret ve kaydet")
    parser.add_argument("--no-pin", action="store_true", help="PIN korumasını kapat (önerilmez)")
    args = parser.parse_args()
    StreamServer(
        port=args.port,
        preferred_monitor=args.monitor,
        fps=args.fps,
        quality=args.quality,
        auto_main_display=not args.no_auto_main,
        pin_guard=PinGuard(enabled=not args.no_pin, pin_override=args.pin, reset=args.reset_pin),
    ).run()


if __name__ == "__main__":
    main()
