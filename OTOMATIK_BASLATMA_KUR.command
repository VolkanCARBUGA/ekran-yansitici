#!/usr/bin/env bash
# ==============================================================================
# Ekran Yansıtıcı — macOS Açılışında Otomatik Başlatma Kurulumu (LaunchAgent)
# Doğrudan Python.app yürütülebilir dosyasını başlatır; böylece macOS
# Erişilebilirlik (Accessibility) ve Ekran Kaydı izinleri doğrudan Python.app
# üzerinden sorunsuz tanınır (bash katmanı izni engellemez).
# ==============================================================================
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
INSTALL_DIR="$HOME/Library/Application Support/EkranYansitici"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/com.ekranyansitici.server.plist"
LOG_DIR="$HOME/Library/Logs/EkranYansitici"

source "$DIR/app/macos_python.sh"

mkdir -p "$PLIST_DIR" "$LOG_DIR"

if [ "$1" = "--kaldir" ] || [ "$1" = "--uninstall" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    rm -rf "$INSTALL_DIR"
    echo "✅ Otomatik başlatma kaldırıldı."
    exit 0
fi

# Eski servisi ve süreçleri temizle
launchctl unload "$PLIST_PATH" 2>/dev/null || true
lsof -ti :8080 | xargs kill -9 2>/dev/null || true
pkill -f "EkranYansitici/server.py" 2>/dev/null || true
sleep 0.3

# TCC (Desktop) iznine takılmaması için Application Support'a kopyala
mkdir -p "$INSTALL_DIR"
rsync -a --delete --exclude venv --exclude __pycache__ "$DIR/app/" "$INSTALL_DIR/"
ensure_venv "$INSTALL_DIR"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ekranyansitici.server</string>

    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_APP_BIN}</string>
        <string>${INSTALL_DIR}/server.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${INSTALL_DIR}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${HOME}/Library/Android/sdk/platform-tools</string>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${LOG_DIR}/server.log</string>

    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/server.err.log</string>
</dict>
</plist>
EOF

# Eski logları temizle
: > "$LOG_DIR/server.log"
: > "$LOG_DIR/server.err.log"

launchctl load "$PLIST_PATH"
sleep 1.8

echo "=========================================================="
echo "✅ OTOMATİK BAŞLATMA KURULDU VE ŞU AN AKTİF!"
echo "----------------------------------------------------------"
echo "• Çalıştırıcı    : $PYTHON_APP_BIN"
echo "• Kurulum dizini : $INSTALL_DIR"
echo "• Loglar         : $LOG_DIR/server.log"
echo "=========================================================="
