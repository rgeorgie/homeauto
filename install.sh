#!/usr/bin/env bash
set -e

# ==========================================================
# HomeAuto Platform - Raspberry Pi Installer
# Target OS: Raspberry Pi OS / Raspbian (Debian-based)
# ==========================================================

echo "=========================================================="
echo "🏡 Installing HomeAuto Platform on Raspberry Pi OS..."
echo "=========================================================="

CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="$(whoami)"

echo "==> Updating apt repositories & installing system dependencies..."
sudo apt-get update -y
sudo apt-get install -y \
  python3-pip \
  python3-venv \
  python3-dev \
  kodi \
  mpv \
  chromium-browser \
  bluez \
  libspa-0.2-bluetooth \
  pulseaudio-utils \
  xdotool \
  unclutter \
  git \
  curl || true

# Install PipeWire / Pulse modules depending on Pi OS distribution
sudo apt-get install -y pipewire-audio wireplumber || sudo apt-get install -y pulseaudio pulseaudio-module-bluetooth || true

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

# Ensure photo directory exists
mkdir -p frontend/assets/photos

echo "==> Installing systemd services & Desktop Autostart entry..."
chmod +x "$CURRENT_DIR/kiosk.sh"

sudo cp systemd/homeauto.service /etc/systemd/system/homeauto.service
sudo cp systemd/homeauto-kiosk.service /etc/systemd/system/homeauto-kiosk.service

# Install XDG Desktop Autostart (works across X11, Wayland, Wayfire, Labwc)
mkdir -p "$HOME/.config/autostart"
cp systemd/homeauto-kiosk.desktop "$HOME/.config/autostart/homeauto-kiosk.desktop"
sed -i "s|/home/pi/homeauto|$CURRENT_DIR|g" "$HOME/.config/autostart/homeauto-kiosk.desktop"

# Adjust user in systemd service if not 'pi'
if [ "$USER_NAME" != "pi" ]; then
  echo "==> Updating service user to $USER_NAME..."
  sudo sed -i "s/User=pi/User=$USER_NAME/g" /etc/systemd/system/homeauto.service
  sudo sed -i "s|/home/pi/homeauto|$CURRENT_DIR|g" /etc/systemd/system/homeauto.service
  sudo sed -i "s/User=pi/User=$USER_NAME/g" /etc/systemd/system/homeauto-kiosk.service
  sudo sed -i "s|/home/pi/homeauto|$CURRENT_DIR|g" /etc/systemd/system/homeauto-kiosk.service
  sudo sed -i "s|/home/pi/.Xauthority|/home/$USER_NAME/.Xauthority|g" /etc/systemd/system/homeauto-kiosk.service
fi

sudo systemctl daemon-reload
sudo systemctl enable homeauto.service
sudo systemctl enable homeauto-kiosk.service

echo "==> Configuring Bluetooth audio permissions..."
sudo usermod -a -G bluetooth,audio "$USER_NAME"

echo ""
echo "=========================================================="
echo "🎉 HomeAuto Platform Installation Complete!"
echo "=========================================================="
echo "Next steps:"
echo "1. Edit your devices & Bluetooth MAC in: $CURRENT_DIR/config.yaml"
echo "2. Start the service: sudo systemctl start homeauto.service"
echo "3. Start the Touchscreen Kiosk: sudo systemctl start homeauto-kiosk.service"
echo "4. Or test run manually: source venv/bin/activate && python -m backend.main"
echo "=========================================================="
