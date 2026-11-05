#!/usr/bin/env bash
set -e

CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="$(whoami)"

echo "==> Configuring HomeAuto as user session service for '$USER_NAME'..."

# 1. Stop and clean up old system-level services
echo "==> Cleaning up system-level services..."
sudo systemctl stop homeauto.service homeauto-kiosk.service 2>/dev/null || true
sudo systemctl disable homeauto.service homeauto-kiosk.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/homeauto.service /etc/systemd/system/homeauto-kiosk.service
sudo systemctl daemon-reload

# 2. Enable lingering so user services start at boot without manual login
echo "==> Enabling user lingering for $USER_NAME..."
loginctl enable-linger "$USER_NAME"

# 3. Create user systemd directory
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$USER_SYSTEMD_DIR"

# 4. Generate user service for Backend Hub
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

# 5. Generate user service for Chromium Touch Kiosk
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

[Install]
WantedBy=default.target
EOF

# 6. Reload and start user services
systemctl --user daemon-reload
systemctl --user enable --now homeauto.service
systemctl --user enable --now homeauto-kiosk.service

echo ""
echo "🎉 HomeAuto is now running in your native user session with full PipeWire & Bluetooth audio access!"
echo "Check status anytime with:"
echo "  systemctl --user status homeauto.service"
echo "  systemctl --user status homeauto-kiosk.service"
