# Ekran Yansıtıcı

**English** · [Türkçe](README.tr.md)

[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey)](#installation)

Mirrors the built-in screen of a laptop with a broken display to an Android tablet and lets you use it by touch. The tablet connects over a USB cable or Wi-Fi, and nothing has to be installed on it: the screen opens in the browser.

It was written to keep a MacBook with a cracked screen in use. Windows support came later.

<p align="center">
  <img src="docs/assets/hero.jpg" alt="A laptop with a shattered screen on a desk; a tablet connected by USB shows the computer's desktop while a finger touches it" width="880">
  <br>
  <sub>Illustrative image, generated with AI.</sub>
</p>

The name is Turkish for "screen mirror". The interface and logs are in Turkish for now; the commands and options below are the same in any language.

## What it does

- When the tablet is plugged in over USB, it sets up an `adb reverse` tunnel and opens the page on the tablet by itself.
- On the same network you can also connect over Wi-Fi. A 6-digit PIN is required in that case.
- Touches become mouse input:
  - Tap → click
  - Double tap → double click
  - Long press → right click
  - Drag → drag and drop
  - Two fingers → zoom
- With an external monitor attached, it moves the main display (menu bar, Dock, taskbar) depending on whether the tablet is connected. Details below.
- It installs as a background service that starts at login and restarts if it stops.

## How the main display is chosen

So that the menu bar and new windows never end up on the broken screen, the main display follows the tablet:

<p align="center">
  <img src="docs/assets/scenarios.en.svg" alt="Tablet only: the tablet is the main display. Tablet and monitor: the tablet is main, the monitor second. Monitor only: the monitor is the main display." width="820">
</p>

| Connected | Main display | Second display |
|---|---|---|
| Tablet only | Tablet | — |
| Tablet and monitor | Tablet | Monitor |
| Monitor only | Monitor | Broken screen |

If the tablet stays disconnected for more than 4 seconds, the main display moves to the monitor, so short dropouts do not make it jump back and forth. The relative arrangement of the displays is kept. Turn this off with `--no-auto-main`.

## Requirements

- **Computer:** macOS 12+ or Windows 10/11
- **Python 3.10+:** on Windows, tick "Add python.exe to PATH" during installation.
- **ADB (USB only):**
  - macOS: `brew install android-platform-tools`
  - Windows: download [Platform Tools](https://developer.android.com/tools/releases/platform-tools) and add it to PATH.
- **Tablet:** Android, Chrome recommended.

To use the tablet over USB, turn on USB debugging once:

1. In **Settings → About tablet**, tap **Build number** seven times.
2. In **Developer options**, turn on **USB debugging**.
3. The first time you plug the tablet in, answer the prompt with **Always allow from this computer**.

## Installation

```bash
git clone https://github.com/VolkanCARBUGA/ekran-yansitici.git
cd ekran-yansitici
```

If you cannot see the screen at all, do these steps with an external monitor, through screen sharing (VNC / Remote Desktop) or over SSH. Once installed, the service starts on its own.

### macOS

```bash
./OTOMATIK_BASLATMA_KUR.command   # install as a service
./BASLAT.command                  # or just run it for now
```

The installer:

- copies the files to `~/Library/Application Support/EkranYansitici`,
- creates a virtual environment (venv),
- adds a LaunchAgent.

On first run, grant two permissions in **System Settings → Privacy & Security**:

- **Screen Recording:** without it the image is black.
- **Accessibility:** without it touch input does nothing.

The app to grant them to is the `Python.app` printed as "Çalıştırıcı" (runner) at the end of the installer. Run the installer once more after granting them.

To uninstall: `./OTOMATIK_BASLATMA_KUR.command --kaldir`

### Windows

Run `OTOMATIK_BASLATMA_KUR.bat`. For the current session only, `BASLAT.bat` is enough.

The installer:

- copies the files to `%LOCALAPPDATA%\EkranYansitici`,
- creates a virtual environment,
- puts a hidden launcher in the Startup folder.

Logs are in `%LOCALAPPDATA%\EkranYansitici\logs\server.log`.

Two things to know:

- **Firewall:** Windows may ask for permission on first start. Allow **Private networks** for Wi-Fi; USB works without it.
- **Elevated windows:** Windows does not let a normal app send clicks to windows running as administrator. If you need to use those by touch, start the server as administrator.

To uninstall: `OTOMATIK_BASLATMA_KUR.bat --kaldir`

## Usage

**USB:** with the service installed, plug in the tablet. The page opens on it within a few seconds.

**Wi-Fi:** on the tablet, open the `http://<ip>:8080` address the server prints at startup and enter the PIN. The tablet remembers it and will not ask again.

Buttons in the bottom-right corner:

- **Full screen:** enters or leaves full screen.
- **Zoom percentage:** resets the zoom.
- **Lock (USB only):** shows the Wi-Fi PIN for ten seconds.

## PIN and security

The server listens on every network interface, so a Wi-Fi connection gets no image and cannot send input until the PIN is entered. USB connections come in through `127.0.0.1` and are not asked for a PIN: the tablet has to be plugged in and authorized for USB debugging.

- **How the PIN is created:** it is generated at random on first run and saved to a settings file. Reinstalling the service does not change it.
  - macOS: `~/.config/ekran-yansitici/ayarlar.json`
  - Windows: `%APPDATA%\EkranYansitici\ayarlar.json`
- **Seeing the PIN:** with a broken screen, tap the lock button on the USB-connected tablet, or check the log file.
- **Remembering it:** after a correct PIN the tablet stores a token. Changing the PIN with `--reset-pin` invalidates old tokens.
- **Lockout:** five wrong attempts from the same IP lock it out for 30 seconds. Further wrong attempts double the lock each time, up to 15 minutes.

The PIN keeps strangers out, but the connection is not encrypted (plain HTTP). On public networks, use USB.

If you find a security issue, please [report it privately](https://github.com/VolkanCARBUGA/ekran-yansitici/security/advisories/new) instead of opening a public issue.

## Options

```
python app/server.py [--port 8080] [--monitor 1] [--fps 60] [--quality 78]
                     [--no-auto-main] [--pin PIN] [--reset-pin] [--no-pin]
```

| Option | Description |
|---|---|
| `--port` | Port (default 8080) |
| `--monitor` | Which display to mirror. The built-in screen is always 1. |
| `--fps` | Target frame rate (default 60) |
| `--quality` | JPEG quality, 1–95 (default 78) |
| `--no-auto-main` | Do not change the main display automatically |
| `--pin` | Set the PIN for this run (not saved). The `EKRAN_PIN` environment variable works too. |
| `--reset-pin` | Generate and save a new PIN |
| `--no-pin` | Turn PIN protection off. Anyone on the same network can then connect. |

To use a specific Python on macOS, run the installer as `EKRAN_PYTHON=/path/to/python3 ./OTOMATIK_BASLATMA_KUR.command`.

## Troubleshooting

| Problem | Fix |
|---|---|
| Black image (macOS) | Grant Screen Recording to `Python.app` and run the installer again. |
| Image works, touch does not (macOS) | Grant Accessibility to `Python.app`. |
| Page does not open when the tablet is plugged in | `adb devices` should list the tablet as `device`. Confirm the USB debugging prompt on the tablet. |
| Log says `ADB: Yok` (ADB: none) | ADB is not installed or not on PATH. |
| I don't know the PIN | Connect the tablet over USB and tap the lock button, or check the log. For a new PIN, run once with `--reset-pin`. |
| Clicks land in the wrong place on Windows | Most likely display scaling (125%/150%). Open an issue with your scaling setting. |
| Main display does not change | With the lid closed the built-in screen is not listed. Look for `Ana ekran →` (main display →) lines in the log. |

**Log files:**

- macOS: `~/Library/Logs/EkranYansitici/server.log`
- Windows: `%LOCALAPPDATA%\EkranYansitici\logs\server.log`

## How it works

The server (`app/server.py`) captures the built-in screen with [mss](https://github.com/BoboTiG/python-mss), encodes it as JPEG with the cursor drawn on top, and sends it to the tablet over a WebSocket. The tablet draws it on a canvas and sends touches back, which the server turns into the operating system's mouse events.

The OS-specific parts live in two files. Both are written with `ctypes`, so nothing needs compiling:

- `app/platform_mac.py`: mouse events, display list and main display switching with CoreGraphics
- `app/platform_win.py`: the same with Win32: `SendInput`, `QueryDisplayConfig`, `ChangeDisplaySettingsEx`

Other files:

- `app/usb_bridge.py`: watches ADB, sets up the tunnel and opens the browser when the tablet is plugged in.
- `app/pin_auth.py`: PIN, token and lockout.
- `app/web/`: the page that opens on the tablet.

## Status

Tested in daily use on macOS. Windows support is new and has seen little testing on real hardware. If something goes wrong, [open an issue](https://github.com/VolkanCARBUGA/ekran-yansitici/issues/new) with your Windows version, display scaling and the contents of `server.log`.

Planned:

- Encrypting the Wi-Fi connection with HTTPS
- An on-screen keyboard on the tablet
- Linux support

## Contributing

Issues and pull requests are welcome. If you change something platform-specific, both platform files have to keep providing the same functions; the list is at the top of `app/platform_layer.py`.

While developing, running the server in a terminal with `./BASLAT.command` (or `BASLAT.bat`) instead of as a service makes errors easier to see.

## License

[MIT](LICENSE)
