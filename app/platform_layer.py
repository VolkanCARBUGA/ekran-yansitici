"""
Platform seçici — çalışılan işletim sistemine göre fare/ekran denetleyicisini yükler.

Her denetleyici aynı arayüzü sağlar:
  get_all_displays, get_display_bounds_by_index, set_main_display,
  get_position, move, move_rel, down, up, click, scroll,
  is_accessibility_trusted, start_keep_awake, stop_keep_awake
"""

import sys

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
PLATFORM_NAME = "Mac" if IS_MAC else "Windows" if IS_WINDOWS else sys.platform

controller = None
try:
    if IS_MAC:
        from platform_mac import MacController
        controller = MacController()
    elif IS_WINDOWS:
        from platform_win import WinController
        controller = WinController()
    else:
        print(f"⚠️  Desteklenmeyen platform: {sys.platform} (yalnızca macOS ve Windows)")
except Exception as e:
    print(f"⚠️  Fare/Ekran kontrolcüsü başlatılamadı: {e}")
