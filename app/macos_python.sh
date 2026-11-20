#!/usr/bin/env bash
# macOS için Python seçimi (BASLAT.command ve OTOMATIK_BASLATMA_KUR.command tarafından source edilir).
#   PY             : kullanılacak python3 (EKRAN_PYTHON ile değiştirilebilir)
#   PYTHON_APP_BIN : izinlerin (Ekran Kaydı / Erişilebilirlik) bağlanacağı yürütülebilir dosya.
#                    Framework derlemelerinde Python.app içindeki ikili kullanılır; böylece
#                    macOS izinleri bash katmanına değil doğrudan Python.app'e tanınır.
# Kullanıcının PATH sırasına (pyenv vb.) dokunma; yalnızca yaygın konumları sona ekle
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:$HOME/Library/Android/sdk/platform-tools"

PY="${EKRAN_PYTHON:-$(command -v python3)}"
if [ -z "$PY" ]; then
    echo "❌ python3 bulunamadı. https://www.python.org/downloads/ adresinden Python 3.10+ kurun."
    exit 1
fi

PY_VER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PYTHON_APP_BIN="$("$PY" -c 'import os, sys
p = os.path.join(sys.base_prefix, "Resources/Python.app/Contents/MacOS/Python")
print(p if os.path.exists(p) else os.path.realpath(sys.executable))')"

# ensure_venv <dizin>: dizin/venv yoksa veya Python sürümü farklıysa oluşturur, bağımlılıkları kurar
ensure_venv() {
    local target="$1"
    local venv_py="$target/venv/bin/python3"
    if [ ! -x "$venv_py" ] || [ "$("$venv_py" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" != "$PY_VER" ]; then
        echo "📦 Sanal ortam oluşturuluyor ($PY_VER)..."
        rm -rf "$target/venv"
        "$PY" -m venv "$target/venv"
    fi
    "$venv_py" -m pip install -q --disable-pip-version-check -r "$target/requirements.txt"
}
