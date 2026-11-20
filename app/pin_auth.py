"""
Wi-Fi bağlantıları için PIN koruması.

  • PIN ilk çalıştırmada rastgele 6 haneli olarak üretilir ve ayar dosyasına kaydedilir
    (kurulum dizininin dışında tutulur; servis yeniden kurulunca PIN değişmez).
  • USB (adb reverse → 127.0.0.1) bağlantıları PIN istemez: kablo fiziksel erişim demektir.
  • Doğru PIN'den sonra istemciye bir jeton verilir; tablet bunu saklar ve bir daha PIN sormaz.
    Jeton PIN'e bağlıdır — PIN değişince tüm eski jetonlar geçersiz olur.
  • Kaba kuvvete karşı: aynı IP'den her 5 yanlış denemede 30 sn, 60 sn, ... (en çok 15 dk) kilit.
"""

import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Optional

MAX_FAILS_PER_ROUND = 5
BASE_LOCK_SECONDS = 30
MAX_LOCK_SECONDS = 15 * 60


def config_path() -> Path:
    """Ayar dosyası: Windows'ta %APPDATA%\\EkranYansitici, diğerlerinde ~/.config/ekran-yansitici."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "EkranYansitici"
    else:
        base = Path.home() / ".config" / "ekran-yansitici"
    return base / "ayarlar.json"


def is_local_address(ip: Optional[str]) -> bool:
    """USB (adb reverse) ve aynı bilgisayardan gelen bağlantılar yerel sayılır."""
    return ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1")


class PinGuard:
    def __init__(self, enabled: bool = True, pin_override: Optional[str] = None, reset: bool = False):
        self.enabled = enabled
        self._path = config_path()
        cfg = self._load()
        changed = False

        if reset or not str(cfg.get("pin", "")).isdigit():
            cfg["pin"] = f"{secrets.randbelow(10**6):06d}"
            changed = True
        if not cfg.get("secret"):
            cfg["secret"] = secrets.token_hex(32)
            changed = True
        if changed:
            self._save(cfg)

        override = (pin_override or os.environ.get("EKRAN_PIN") or "").strip()
        self.pin = override or cfg["pin"]
        self._secret = bytes.fromhex(cfg["secret"])
        # ip -> [ardışık yanlış sayısı, kilit bitiş zamanı (monotonic)]
        self._fails: dict[str, list[float]] = {}

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, cfg: dict):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            if sys.platform != "win32":
                os.chmod(self._path, 0o600)
        except Exception as e:
            print(f"⚠️  PIN ayar dosyası yazılamadı ({self._path}): {e}")

    def requires_auth(self, ip: Optional[str]) -> bool:
        return self.enabled and not is_local_address(ip)

    def token(self) -> str:
        return hmac.new(self._secret, self.pin.encode(), hashlib.sha256).hexdigest()

    def check_token(self, token: Optional[str]) -> bool:
        return bool(token) and hmac.compare_digest(str(token), self.token())

    def locked_for(self, ip: str) -> int:
        entry = self._fails.get(ip)
        if not entry:
            return 0
        return max(0, int(round(entry[1] - time.monotonic())))

    def try_pin(self, ip: str, pin: Optional[str]) -> tuple[bool, int, int]:
        """PIN'i dener. Dönüş: (başarılı mı, kilit süresi sn, kilide kalan deneme)."""
        locked = self.locked_for(ip)
        if locked > 0:
            return False, locked, 0
        if pin is not None and hmac.compare_digest(str(pin).strip(), self.pin):
            self._fails.pop(ip, None)
            return True, 0, MAX_FAILS_PER_ROUND

        entry = self._fails.setdefault(ip, [0, 0.0])
        entry[0] += 1
        fails = int(entry[0])
        if fails % MAX_FAILS_PER_ROUND == 0:
            rounds = fails // MAX_FAILS_PER_ROUND
            lock = min(MAX_LOCK_SECONDS, BASE_LOCK_SECONDS * (2 ** (rounds - 1)))
            entry[1] = time.monotonic() + lock
            print(f"🔒  {ip} için {MAX_FAILS_PER_ROUND} yanlış PIN denemesi — {lock} sn kilit")
            return False, lock, 0
        return False, 0, MAX_FAILS_PER_ROUND - (fails % MAX_FAILS_PER_ROUND)
