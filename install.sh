#!/usr/bin/env bash
set -e

# ==========================================================
# HomeAuto Platform - Interactive Multi-Scenario Installer
# Target OS: Debian / Ubuntu / Raspberry Pi OS / LXC
# ==========================================================

CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="$(whoami)"

# Privilege check
if [ "$EUID" -eq 0 ]; then
  SUDO=""
else
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "Error: sudo is required for non-root users. Please install sudo or run as root."
    exit 1
  fi
fi

# Helper functions for UI
print_header() {
  echo "=========================================================="
  echo "🏡 HomeAuto Platform Installer"
  echo "=========================================================="
}

install_system_packages() {
  local packages=("$@")
  echo "==> Updating package lists & installing dependencies..."
  $SUDO apt-get update -y
  $SUDO apt-get install -y "${packages[@]}"
}

setup_python_venv() {
  echo "==> Setting up Python virtual environment..."
  cd "$CURRENT_DIR"
  if [ ! -d "venv" ]; then
    python3 -m venv venv
  fi

  source venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt

  # Create default config if missing
  if [ ! -f "config.yaml" ]; then
    echo "==> Creating config.yaml from config.example.yaml..."
    cp config.example.yaml config.yaml
  fi

  # Ensure asset directories exist
  mkdir -p frontend/assets/photos frontend/assets/fireplace
}

setup_port80_permissions() {
  if [ "$EUID" -ne 0 ]; then
    echo "==> Configuring unprivileged port 80 access..."
    echo "net.ipv4.ip_unprivileged_port_start=80" | $SUDO tee /etc/sysctl.d/99-homeauto-port80.conf >/dev/null
    $SUDO sysctl -q --system >/dev/null 2>&1 || true
  fi
}

setup_server_service() {
  echo "==> Setting up HomeAuto Server systemd service..."

  if [ "$EUID" -eq 0 ]; then
    # Root installation (typical in LXC / server) -> system-level service
    cat > /etc/systemd/system/homeauto.service <<EOF
[Unit]
Description=HomeAuto Platform Backend Hub
After=network.target

[Service]
Type=simple
WorkingDirectory=${CURRENT_DIR}
ExecStart=${CURRENT_DIR}/venv/bin/python -m backend.main
Restart=always
RestartSec=3
TimeoutStopSec=5
KillMode=control-group
KillSignal=SIGTERM
SendSIGKILL=yes
FinalKillSignal=SIGKILL
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now homeauto.service
    echo "==> Systemd service 'homeauto.service' enabled and started (system level)."
  else
    # Non-root user installation -> user systemd service with lingering
    loginctl enable-linger "$USER_NAME" 2>/dev/null || true
    USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
    mkdir -p "$USER_SYSTEMD_DIR"

    cat > "$USER_SYSTEMD_DIR/homeauto.service" <<EOF
[Unit]
Description=HomeAuto Platform Backend Hub
After=network.target sound.target pipewire.service wireplumber.service
Wants=pipewire.service wireplumber.service

[Service]
Type=simple
WorkingDirectory=${CURRENT_DIR}
ExecStart=${CURRENT_DIR}/venv/bin/python -m backend.main
Restart=always
RestartSec=3
TimeoutStopSec=5
KillMode=control-group
KillSignal=SIGTERM
SendSIGKILL=yes
FinalKillSignal=SIGKILL
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now homeauto.service
    echo "==> User systemd service 'homeauto.service' enabled and started."
  fi
}

setup_zram_swap() {
  if [ "$EUID" -eq 0 ] || [ -n "$SUDO" ]; then
    echo "==> Configuring zram compressed swap..."
    if ! dpkg -s systemd-zram-generator >/dev/null 2>&1 && ! dpkg -s zram-tools >/dev/null 2>&1; then
      $SUDO apt-get install -y systemd-zram-generator >/dev/null 2>&1 || $SUDO apt-get install -y zram-tools >/dev/null 2>&1 || true
    fi
    if dpkg -s systemd-zram-generator >/dev/null 2>&1; then
      printf '[zram0]\nzram-size = ram / 2\ncompression-algorithm = zstd\nswap-priority = 100\n' | $SUDO tee /etc/systemd/zram-generator.conf >/dev/null
      $SUDO systemctl daemon-reload 2>/dev/null || true
      $SUDO systemctl restart systemd-zram-setup@zram0.service 2>/dev/null || true
    fi
    $SUDO sysctl -q vm.swappiness=100 2>/dev/null || true
    echo "vm.swappiness=100" | $SUDO tee /etc/sysctl.d/98-homeauto-swap.conf >/dev/null 2>&1 || true
  fi
}

setup_pi_agent_service() {
  # Kiosk-only Pi: small local service so the web UI can scan/pair/route the Pi's own Bluetooth speaker
  echo "==> Setting up Pi Bluetooth agent (backend/pi_agent.py)..."
  cd "$CURRENT_DIR"
  if [ ! -d "venv" ]; then
    python3 -m venv venv
  fi
  "$CURRENT_DIR/venv/bin/pip" install --upgrade pip >/dev/null
  "$CURRENT_DIR/venv/bin/pip" install fastapi "uvicorn[standard]" pydantic pyyaml

  if [ "$EUID" -ne 0 ]; then
    loginctl enable-linger "$USER_NAME" 2>/dev/null || true
    USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
    mkdir -p "$USER_SYSTEMD_DIR"
    cat > "$USER_SYSTEMD_DIR/homeauto-agent.service" <<EOF
[Unit]
Description=HomeAuto Pi Bluetooth Agent
After=pipewire.service wireplumber.service
Wants=pipewire.service wireplumber.service

[Service]
Type=simple
WorkingDirectory=${CURRENT_DIR}
ExecStart=${CURRENT_DIR}/venv/bin/python -m backend.pi_agent
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now homeauto-agent.service 2>/dev/null || true
    echo "==> User systemd service 'homeauto-agent.service' enabled (listens on 127.0.0.1:8765)."
  else
    echo "==> Run as a normal user (not root) to install the agent service; Bluetooth audio needs the user's PipeWire session."
  fi
}

setup_kiosk_service() {
  local server_url="$1"
  echo "==> Setting up Chromium Touchscreen Kiosk..."

  chmod +x "$CURRENT_DIR/kiosk.sh"

  # Save persistent server URL if provided
  if [ -n "$server_url" ]; then
    echo "export HOMEAUTO_SERVER=\"$server_url\"" > "$CURRENT_DIR/.kiosk_env"
    echo "==> Saved Server URL to $CURRENT_DIR/.kiosk_env: $server_url"
  else
    rm -f "$CURRENT_DIR/.kiosk_env"
  fi

  # Install XDG Desktop Autostart entry
  mkdir -p "$HOME/.config/autostart"
  cat > "$HOME/.config/autostart/homeauto-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=HomeAuto Kiosk
Comment=15" Touchscreen Dashboard Kiosk
Exec=${CURRENT_DIR}/kiosk.sh
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

  # Install systemd user services for kiosk
  if [ "$EUID" -ne 0 ]; then
    loginctl enable-linger "$USER_NAME" 2>/dev/null || true
    USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
    mkdir -p "$USER_SYSTEMD_DIR"

    cat > "$USER_SYSTEMD_DIR/homeauto-kiosk.service" <<EOF
[Unit]
Description=HomeAuto 15" Touchscreen Chromium Kiosk Display
After=homeauto.service graphical-session.target
Wants=homeauto.service

[Service]
Type=simple
WorkingDirectory=${CURRENT_DIR}
Environment=DISPLAY=:0
Environment=WAYLAND_DISPLAY=wayland-0
ExecStart=${CURRENT_DIR}/kiosk.sh
Restart=always
RestartSec=3
TimeoutStopSec=5
KillMode=control-group
KillSignal=SIGTERM
SendSIGKILL=yes
FinalKillSignal=SIGKILL
MemoryHigh=450M
MemoryMax=550M

[Install]
WantedBy=default.target
EOF

    cat > "$USER_SYSTEMD_DIR/homeauto-kiosk-restart.service" <<EOF
[Unit]
Description=Restart HomeAuto kiosk browser to free memory

[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl --user restart homeauto-kiosk.service
EOF

    cat > "$USER_SYSTEMD_DIR/homeauto-kiosk-restart.timer" <<EOF
[Unit]
Description=Nightly HomeAuto kiosk browser restart

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=false

[Install]
WantedBy=timers.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable --now homeauto-kiosk.service 2>/dev/null || true
    systemctl --user enable --now homeauto-kiosk-restart.timer 2>/dev/null || true
  fi

  setup_zram_swap
}

# Scenario Implementations

run_scenario_server_only() {
  echo ""
  echo "📦 Installing Scenario 1: Headless Server Only (LXC / VM / Server)..."
  echo "----------------------------------------------------------"

  # Minimal packages for backend
  local pkgs=(
    python3-pip
    python3-venv
    python3-dev
    ffmpeg
    curl
    git
  )
  install_system_packages "${pkgs[@]}"

  setup_port80_permissions
  setup_python_venv
  setup_server_service

  # Get local IP
  LOCAL_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  LOCAL_IP="${LOCAL_IP:-<server-ip>}"

  echo ""
  echo "=========================================================="
  echo "🎉 HomeAuto Headless Server Installation Complete!"
  echo "=========================================================="
  echo "Access the web dashboard at: http://${LOCAL_IP}:80"
  echo "API Health Check:            http://${LOCAL_IP}:80/api/status"
  echo ""
  echo "Manage the server service:"
  if [ "$EUID" -eq 0 ]; then
    echo "  systemctl status homeauto.service"
    echo "  systemctl restart homeauto.service"
  else
    echo "  systemctl --user status homeauto.service"
    echo "  systemctl --user restart homeauto.service"
  fi
  echo "=========================================================="
}

run_scenario_kiosk_only() {
  local server_url="$1"

  echo ""
  echo "📺 Installing Scenario 2: Remote Touchscreen Kiosk Only (Raspberry Pi)..."
  echo "----------------------------------------------------------"

  if [ -z "$server_url" ]; then
    echo ""
    echo "Enter the URL of your remote HomeAuto Server (e.g. running on LXC container):"
    read -r -p "Server URL [http://192.168.1.100:80]: " input_url
    input_url="${input_url:-http://192.168.1.100:80}"
    # Ensure scheme
    if [[ ! "$input_url" =~ ^https?:// ]]; then
      input_url="http://${input_url}"
    fi
    server_url="${input_url%/}"
  fi

  echo "==> Configuring Kiosk to connect to: $server_url"

  # Kiosk display packages
  $SUDO apt-get update -y
  $SUDO apt-get install -y \
    chromium-browser \
    xdotool \
    unclutter \
    curl \
    git || $SUDO apt-get install -y chromium xdotool unclutter curl git

  # Bluetooth audio packages for the local speaker on the Pi
  $SUDO apt-get install -y python3-venv bluez libspa-0.2-bluetooth pulseaudio-utils || true
  $SUDO apt-get install -y pipewire-audio wireplumber || $SUDO apt-get install -y pulseaudio pulseaudio-module-bluetooth || true
  if [ "$EUID" -ne 0 ]; then
    $SUDO usermod -a -G bluetooth,audio "$USER_NAME" 2>/dev/null || true
  fi

  setup_pi_agent_service
  setup_kiosk_service "$server_url"

  echo ""
  echo "=========================================================="
  echo "🎉 HomeAuto Remote Kiosk Installation Complete!"
  echo "=========================================================="
  echo "Target Server URL: $server_url"
  echo ""
  echo "To launch Kiosk manually:"
  echo "  ./kiosk.sh"
  echo ""
  echo "Manage Kiosk service:"
  echo "  systemctl --user status homeauto-kiosk.service"
  echo "  systemctl --user restart homeauto-kiosk.service"
  echo "=========================================================="
}

run_scenario_all_in_one() {
  echo ""
  echo "🚀 Installing Scenario 3: All-in-One Standalone (Server + Kiosk on Raspberry Pi)..."
  echo "----------------------------------------------------------"

  # All packages
  local pkgs=(
    python3-pip
    python3-venv
    python3-dev
    kodi
    mpv
    ffmpeg
    chromium-browser
    bluez
    libspa-0.2-bluetooth
    pulseaudio-utils
    xdotool
    unclutter
    git
    curl
  )
  install_system_packages "${pkgs[@]}" || {
    # Fallback for systems where chromium-browser is named chromium
    $SUDO apt-get install -y chromium || true
  }

  $SUDO apt-get install -y pipewire-audio wireplumber || $SUDO apt-get install -y pulseaudio pulseaudio-module-bluetooth || true

  setup_port80_permissions
  setup_python_venv
  setup_server_service
  setup_kiosk_service ""

  if [ "$EUID" -ne 0 ]; then
    $SUDO usermod -a -G bluetooth,audio "$USER_NAME" 2>/dev/null || true
  fi

  echo ""
  echo "=========================================================="
  echo "🎉 HomeAuto All-in-One Installation Complete!"
  echo "=========================================================="
  echo "Local Dashboard: http://localhost:80"
  echo ""
  echo "Manage services:"
  echo "  systemctl --user status homeauto.service"
  echo "  systemctl --user status homeauto-kiosk.service"
  echo "=========================================================="
}

# CLI Argument Parsing
print_header

if [ "$1" = "--server" ] || [ "$1" = "-s" ] || [ "$1" = "1" ]; then
  run_scenario_server_only
  exit 0
elif [ "$1" = "--kiosk" ] || [ "$1" = "-k" ] || [ "$1" = "2" ]; then
  run_scenario_kiosk_only "$2"
  exit 0
elif [ "$1" = "--all" ] || [ "$1" = "-a" ] || [ "$1" = "3" ]; then
  run_scenario_all_in_one
  exit 0
elif [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
  echo "Usage: ./install.sh [OPTION] [SERVER_URL]"
  echo ""
  echo "Options:"
  echo "  --server, -s, 1         Install Headless Server only (LXC / VM / Server)"
  echo "  --kiosk,  -k, 2 [URL]   Install Touchscreen Kiosk only (Raspberry Pi)"
  echo "  --all,    -a, 3         Install All-in-One Standalone (Server + Kiosk on Pi)"
  echo "  --help,   -h            Show this help message"
  echo ""
  echo "If no options are given, an interactive selection menu will be displayed."
  exit 0
fi

# Interactive Menu
echo "Please select your installation scenario:"
echo ""
echo "  1) 📦 Headless Server ONLY (LXC container, Proxmox, VM, NAS, PC)"
echo "        • Installs Python backend, FastAPI, and media APIs"
echo "        • No GUI / Chromium / Kiosk installed"
echo "        • Runs as a background systemd service"
echo ""
echo "  2) 📺 Remote Touchscreen Kiosk ONLY (Raspberry Pi display)"
echo "        • Installs Chromium kiosk display & autostart"
echo "        • Connects over HTTP to your remote HomeAuto Server"
echo "        • No backend server running on this device"
echo ""
echo "  3) 🚀 All-in-One Standalone (Server + Kiosk on Raspberry Pi)"
echo "        • Installs both Backend Server and Local Touchscreen Display"
echo "        • Configures Kodi, Bluetooth Audio, and Kiosk autostart"
echo ""
echo "  4) ❌ Exit"
echo ""

while true; do
  read -r -p "Enter choice [1-4]: " choice
  case "$choice" in
    1)
      run_scenario_server_only
      break
      ;;
    2)
      run_scenario_kiosk_only
      break
      ;;
    3)
      run_scenario_all_in_one
      break
      ;;
    4|q|Q)
      echo "Installation cancelled."
      exit 0
      ;;
    *)
      echo "Invalid choice. Please select 1, 2, 3, or 4."
      ;;
  esac
done
