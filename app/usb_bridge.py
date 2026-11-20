#!/usr/bin/env python3
"""
Otomatik Android USB Köprüsü (ADB Reverse + Otomatik Tarayıcı Açma).
Bilgisayar açık olduğu sürece arka planda 1 saniyede bir USB portunu izler.
Android tablet takıldığı anda:
  1. `adb reverse tcp:<port> tcp:<port>` tünelini otomatik kurar.
  2. Tablet ekranını uyandırır.
  3. Tablette Chrome (veya varsayılan tarayıcı) üzerinden `http://127.0.0.1:<port>`
     adresini kendiliğinden açar — bilgisayarda hiçbir şeye tıklamanız gerekmez.
"""

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional


IS_WINDOWS = sys.platform == "win32"
# Windows'ta arka planda (pythonw) çalışırken her adb çağrısında konsol penceresi açılmasın
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0


def find_adb() -> Optional[str]:
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))
        candidates = [
            str(Path(local) / "Android/Sdk/platform-tools/adb.exe"),
            str(Path(__file__).resolve().parent / "platform-tools/adb.exe"),
            r"C:\platform-tools\adb.exe",
            shutil.which("adb") or "",
        ]
    else:
        candidates = [
            str(Path.home() / "Library/Android/sdk/platform-tools/adb"),
            "/opt/homebrew/bin/adb",
            "/usr/local/bin/adb",
            shutil.which("adb") or "",
        ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


class UsbAdbBridge(threading.Thread):
    def __init__(self, port: int = 8080, auto_open_browser: bool = True, on_connect=None):
        super().__init__(daemon=True)
        self.port = port
        self.auto_open_browser = auto_open_browser
        self.on_connect = on_connect
        self.adb_bin = find_adb()
        self.running = True
        self._lock = threading.Lock()
        self._devices: dict[str, dict] = {}
        self._opened_serials: set[str] = set()

    @property
    def is_available(self) -> bool:
        return self.adb_bin is not None

    def get_devices(self) -> list[dict]:
        with self._lock:
            return list(self._devices.values())

    def _run_adb(self, args: list[str], timeout: float = 3.0) -> tuple[int, str]:
        if not self.adb_bin:
            return 1, ""
        try:
            proc = subprocess.run(
                [self.adb_bin, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=_NO_WINDOW,
            )
            return proc.returncode, proc.stdout.strip()
        except Exception:
            return 1, ""

    def _get_model(self, serial: str) -> str:
        code, out = self._run_adb(["-s", serial, "shell", "getprop", "ro.product.model"])
        if code == 0 and out:
            return out
        return f"Android ({serial[:8]})"

    def _setup_reverse(self, serial: str) -> bool:
        code, _ = self._run_adb(["-s", serial, "reverse", f"tcp:{self.port}", f"tcp:{self.port}"])
        return code == 0

    def open_on_device(self, serial: str) -> bool:
        url = f"http://127.0.0.1:{self.port}"
        # 1. Tablet uyuyorsa ekranı uyandır
        self._run_adb(["-s", serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP"], timeout=2.0)

        # 2. Önce Chrome ile açmayı dene (WebCodecs H.264 + Tam Ekran en stabil Chrome'da)
        code, _ = self._run_adb([
            "-s", serial, "shell", "am", "start",
            "-n", "com.android.chrome/com.google.android.apps.chrome.Main",
            "-a", "android.intent.action.VIEW",
            "-d", url,
        ], timeout=4.0)
        if code == 0:
            return True

        # 3. Chrome yoksa varsayılan tarayıcıyla aç
        code, _ = self._run_adb([
            "-s", serial, "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", url,
        ], timeout=4.0)
        return code == 0

    def run(self):
        if not self.adb_bin:
            return

        # ADB sunucusunun ayakta olduğundan emin ol
        self._run_adb(["start-server"], timeout=5.0)

        while self.running:
            code, out = self._run_adb(["devices"], timeout=3.0)
            current_serials: set[str] = set()

            if code == 0 and out:
                for line in out.splitlines()[1:]:
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[1] == "device":
                        serial = parts[0]
                        current_serials.add(serial)

                        with self._lock:
                            known = serial in self._devices

                        if not known:
                            model = self._get_model(serial)
                            ok = self._setup_reverse(serial)
                            with self._lock:
                                self._devices[serial] = {
                                    "serial": serial,
                                    "model": model,
                                    "reverse_ok": ok,
                                    "url": f"http://127.0.0.1:{self.port}",
                                }
                            if ok:
                                print(f"🔌  USB Android tablet algılandı: {model} → {url_info(self.port)}")
                                if self.on_connect:
                                    try:
                                        self.on_connect(serial, model)
                                    except Exception:
                                        pass
                                if self.auto_open_browser and serial not in self._opened_serials:
                                    self._opened_serials.add(serial)
                                    opened = self.open_on_device(serial)
                                    if opened:
                                        print(f"🌐  Tablette ekran sayfası otomatik açıldı: http://127.0.0.1:{self.port}")
                        else:
                            # Tünelin canlı kalmasını garanti et
                            self._setup_reverse(serial)

            with self._lock:
                removed = [s for s in self._devices if s not in current_serials]
                for s in removed:
                    info = self._devices.pop(s, None)
                    self._opened_serials.discard(s)
                    if info:
                        print(f"🔌  USB Android tablet ayrıldı: {info.get('model', s)}")

            time.sleep(1.5)

    def stop(self):
        self.running = False


def url_info(port: int) -> str:
    return f"http://127.0.0.1:{port}"
