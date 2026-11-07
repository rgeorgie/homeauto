#!/usr/bin/env bash
set -e

CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="$(whoami)"

echo "==> Configuring HomeAuto as user session service for '$USER_NAME'..."

# 0. Allow non-root user services to bind port 80, and move an old 8080 config to port 80
echo "==> Allowing user services to bind port 80..."
echo "net.ipv4.ip_unprivileged_port_start=80" | sudo tee /etc/sysctl.d/99-homeauto-port80.conf >/dev/null
sudo sysctl -q --system >/dev/null || true
if [ -f "$CURRENT_DIR/config.yaml" ]; then
  sed -i -E '/^server:/,/^[a-z]/ s/^( *port: *)8080( |$)/\180\2/' "$CURRENT_DIR/config.yaml"
fi

# 1. Stop and clean up old system-level services
echo "==> Cleaning up system-level services..."
sudo systemctl stop homeauto.service homeauto-kiosk.service 2>/dev/null || true
sudo systemctl disable homeauto.service homeauto-kiosk.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/homeauto.service /etc/systemd/system/homeauto-kiosk.service
sudo systemctl daemon-reload

# 2. Kill any old lingering python backend processes
echo "==> Stopping any old backend instances..."
# "[b]ackend.main" keeps pkill from matching its own sudo/shell command line
sudo pkill -9 -f "[b]ackend\.main" 2>/dev/null || true
sleep 1

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
# Chromium grows over time: reclaim above High, kill (and auto-restart) above Max
MemoryHigh=450M
MemoryMax=550M

[Install]
WantedBy=default.target
EOF

# 5b. Restart the kiosk browser every night to release leaked memory
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

# 5c. zram compressed swap (much faster than SD-card swap on a 1 GB board)
echo "==> Enabling zram swap..."
if ! dpkg -s systemd-zram-generator >/dev/null 2>&1 && ! dpkg -s zram-tools >/dev/null 2>&1; then
  sudo apt-get install -y systemd-zram-generator >/dev/null 2>&1 || sudo apt-get install -y zram-tools >/dev/null 2>&1 || true
fi
if dpkg -s systemd-zram-generator >/dev/null 2>&1; then
  printf '[zram0]\nzram-size = ram / 2\ncompression-algorithm = zstd\nswap-priority = 100\n' | sudo tee /etc/systemd/zram-generator.conf >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl restart systemd-zram-setup@zram0.service 2>/dev/null || true
fi
sudo sysctl -q vm.swappiness=100 2>/dev/null || true
echo "vm.swappiness=100" | sudo tee /etc/sysctl.d/98-homeauto-swap.conf >/dev/null

# 6. Reload and start user services
systemctl --user daemon-reload
systemctl --user enable --now homeauto.service
systemctl --user enable --now homeauto-kiosk.service
systemctl --user enable --now homeauto-kiosk-restart.timer

echo ""
echo "🎉 HomeAuto is now running in your native user session with full PipeWire & Bluetooth audio access!"
echo "Check status anytime with:"
echo "  systemctl --user status homeauto.service"
echo "  systemctl --user status homeauto-kiosk.service"
