# 🏡 HomeAuto Platform

A complete, modern, touchscreen-optimized Home Automation Hub built for **Raspberry Pi OS (Raspbian)** with a **15" Touchscreen** and **Bluetooth Surround Sound**.

---

## 🌟 Key Features

1. **💡 SmartLife & Tuya Device Connectivity**
   - **Ultra-fast Local Socket Control** via `tinytuya` (no cloud latency, works offline).
   - **Cloud API Fallback** via Tuya Open API for discovery and remote sync.
   - Interactive dashboard widgets: toggles for switches, sockets, smart plugs, and brightness sliders for dimmable lights/LEDs.

2. **📱 15" Touchscreen Optimized Interface**
   - Sleek dark OLED/glassmorphism UI with large touch targets.
   - Works in full-screen **Chromium Kiosk Mode** on the 15" touchscreen display.
   - Real-time reactive state updates over WebSockets (instant sync between touchscreen and phone/laptop browsers).

3. **🖼️ Ambient Screensaver with Glanceable Cards & YouTube Audio**
   - Auto-activates after configurable idle period (e.g. 2 minutes).
   - **Photo Slideshow**: Cycles through local photos (`frontend/assets/photos`) or curated Unsplash HD nature collections with smooth cross-fading.
   - **Glanceable Cards**: Giant OLED clock, live weather forecast, active SmartLife devices count, and Raspberry Pi CPU temperature.
   - **Background Audio**: Integrated YouTube audio streamer (Lofi, Jazz, Ambient nature sounds or custom YouTube URL) with volume controls.
   - **Instant Wake**: Tap anywhere on the 15" touchscreen to wake up.

4. **🛠️ Admin Setup & Control Center Web Panel**
   - **Device Management**: Add, edit, test local connection, and delete SmartLife / Tuya devices, smart panels, and switches in real-time.
   - **Bluetooth Surround Audio Setup**: Configure target MAC, auto-reconnect supervisor, default volume.
   - **Kodi Settings & Connectivity Tester**: Configure host/port, test connection with real-time ping.
   - **Screensaver & YouTube Audio Stream Manager**: Add custom YouTube background streams, set idle timeout, photo folder, and glanceable widget toggles.
   - **Weather & Geolocation**: Auto-detect your latitude & longitude with 1-click.
   - **Live Hot-Reload**: Save changes directly to `config.yaml` with automatic hot-reloading of all backend workers without restarting the service.

5. **🎬 Kodi Integration for TV & Movies**
   - One-touch launcher to start Kodi on your display.
   - Live "Now Playing" playback banner and media controls.
   - Full touch D-Pad remote control (Up, Down, Left, Right, OK, Back, Home, Menu).

5. **🔊 Bluetooth Surround Sound Audio Routing**
   - Auto-reconnect supervisor for your Bluetooth soundbar or surround speaker setup.
   - Real-time volume slider and master sink control.
   - Device scanning and pairing interface.

6. **⚙️ Hardware Telemetry**
   - Live monitoring of Raspberry Pi CPU usage, CPU Temperature (`vcgencmd`), RAM utilization, and IP address.

---

## 🛠️ Hardware Requirements

| Hardware Component | Details & Recommendation |
| :--- | :--- |
| **Raspberry Pi** | Raspberry Pi 4 (4GB/8GB) or Raspberry Pi 5 running **Raspberry Pi OS (64-bit)** |
| **15" Touchscreen** | HDMI Video + USB Touchscreen (Capacitive Touch recommended) |
| **Bluetooth Audio** | Any Bluetooth soundbar, surround sound system, or wireless speaker |
| **Power Supply** | Official 15W/27W USB-C Raspberry Pi Power Supply |

---

## 🚀 Interactive Installation (LXC, Raspberry Pi, Debian / Ubuntu)

HomeAuto features an interactive installer supporting three deployment scenarios:

```bash
# 1. Clone repository
git clone https://github.com/rgeorgie/homeauto.git
cd homeauto

# 2. Make installer executable & run
chmod +x install.sh
./install.sh
```

The installer will prompt you to select your setup:

```
  1) 📦 Headless Server ONLY (LXC container, Proxmox, VM, NAS, Server)
        • Installs Python backend, FastAPI, and media APIs (no GUI/Chromium)
        • Configures & enables background systemd service on port 80

  2) 📺 Remote Touchscreen Kiosk ONLY (Raspberry Pi display)
        • Installs Chromium kiosk display & autostart
        • Connects over HTTP to your remote HomeAuto Server (e.g. LXC container)
        • No local Python server needed on the Pi

  3) 🚀 All-in-One Standalone (Server + Kiosk on Raspberry Pi)
        • Installs both Backend Server and Local Touchscreen Display
        • Configures Kodi, Bluetooth Audio, and Kiosk autostart

  4) ❌ Exit
```

### Non-Interactive / Scripted Usage
You can also run the installer directly with flags or arguments:
```bash
# Install Headless Server (LXC / VM)
./install.sh --server

# Install Remote Kiosk pointing to your LXC Server IP
./install.sh --kiosk http://192.168.1.50:80

# Install All-in-One Standalone
./install.sh --all
```

---

## 🐳 Docker Headless Server + Remote Pi Kiosk (Alternative)

You can also run the backend headless via Docker:

### 1. Run Backend via Docker (LXC / x86 / VM)
```bash
cp config.example.yaml config.yaml
docker compose up -d
```

### 2. Connect Raspberry Pi Screen & Audio (HTTP)
On the Raspberry Pi:
```bash
./install.sh --kiosk http://<SERVER_IP>:80
```
- **Display**: Chromium renders the full interactive dashboard and ambient screensaver.
- **Sound**: Radio stations and background streams play natively inside the Pi's browser (HTML5 audio) through the Pi's HDMI, 3.5mm jack, or connected Bluetooth speaker.

---

## ⚙️ Configuration (`config.yaml`)

Copy `config.example.yaml` to `config.yaml` and configure your devices:

```yaml
server:
  host: "0.0.0.0"
  port: 80

# SmartLife (Tuya) Devices
tuya:
  mode: "local"
  devices:
    - id: "bf0123456789abcdef"
      name: "Living Room Light"
      ip: "192.168.0.101"
      local_key: "0123456789abcdef"
      version: 3.3
      type: "light" # light, socket, switch
      room: "Living Room"

# Bluetooth Surround Sound
bluetooth_audio:
  enabled: true
  target_mac: "00:11:22:33:44:55" # MAC of your surround soundbar
  device_name: "Surround Soundbar"
  auto_reconnect: true
  default_volume: 70

# Kodi Integration
kodi:
  enabled: true
  host: "127.0.0.1"
  port: 8080  # Kodi web server port (must differ from HomeAuto port 80)
  launch_command: "kodi-standalone"

# Ambient Screensaver
screensaver:
  enabled: true
  idle_timeout_seconds: 120
  photo_transition_seconds: 15
  photo_directory: "./frontend/assets/photos"
  youtube_audio:
    enabled: true
    volume: 50
```

### 💡 How to get Tuya / SmartLife Local Keys?
You can scan your local network for your SmartLife devices using the built-in TinyTuya wizard:
```bash
source venv/bin/activate
python -m tinytuya wizard
```
This generates `devices.json` with all Device IDs, IP addresses, and `local_key`s.

---

## 🖥️ Running Manually / In Development

```bash
# Activate environment
source venv/bin/activate

# Start backend server
python -m backend.main
```

Open your browser at: `http://localhost` (or `http://<raspberry-pi-ip>` from your phone/laptop).

---

## 📺 Touchscreen Chromium Kiosk Mode

The platform includes a dedicated [`kiosk.sh`](kiosk.sh:1) launcher compatible with both **X11** and modern Raspberry Pi OS **Wayland (Wayfire / Labwc)** compositors.

### Starting Kiosk Mode:
1. **Autostart on Boot (Desktop Session)**:
   The installer creates `~/.config/autostart/homeauto-kiosk.desktop`. When the Pi boots into the desktop, the 15" touchscreen automatically starts in fullscreen kiosk mode.

2. **Starting / Testing manually:**
   ```bash
   ./kiosk.sh
   ```

3. **Or via systemd:**
   ```bash
   systemctl --user restart homeauto.service
   systemctl --user restart homeauto-kiosk.service
   ```

---

## 📁 Project Architecture

```
homeauto/
├── config.example.yaml        # Full configuration template
├── install.sh                 # Raspberry Pi OS auto-installer
├── requirements.txt           # Python dependencies
├── backend/
│   ├── main.py                # FastAPI server & WebSocket hub
│   ├── config.py              # Configuration manager (YAML/Pydantic)
│   ├── tuya_manager.py        # SmartLife/Tuya Local Socket & Cloud controller
│   ├── bt_audio_manager.py    # Bluetooth audio connection & volume manager
│   ├── kodi_manager.py        # Kodi JSON-RPC API client & launcher
│   ├── media_player.py        # YouTube / Ambient audio stream manager (yt-dlp/mpv)
│   ├── screensaver_manager.py # Photo slideshow & ambient data manager
│   └── system_manager.py      # Pi telemetry (CPU, Temp, Memory, Screen power)
├── frontend/
│   ├── index.html             # Touchscreen Dashboard & Web App
│   ├── css/
│   │   └── style.css          # Touch-optimized dark glassmorphism theme
│   └── js/
│       ├── app.js             # Core UI, router, WebSockets & clock
│       ├── tuya_cards.js      # Device widgets & controls
│       ├── screensaver.js     # Screensaver engine & YouTube audio controls
│       ├── kodi.js            # Kodi launcher & remote D-Pad
│       └── bt_audio.js        # Bluetooth sound selector & volume
└── systemd/
    ├── homeauto.service       # Backend hub systemd service
    └── homeauto-kiosk.service # Touchscreen Kiosk systemd service
```

---

## 📄 License
MIT License. Built for home automation enthusiasts!
