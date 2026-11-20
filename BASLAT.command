#!/usr/bin/env bash
# Ekran Yansıtıcı — Manuel Başlatıcı (macOS, USB + Wi-Fi)
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$DIR/app/macos_python.sh"
ensure_venv "$DIR/app"
exec "$PYTHON_APP_BIN" "$DIR/app/server.py" "$@"
