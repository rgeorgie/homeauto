#!/usr/bin/env bash
set -e

CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="$(whoami)"
USER_UID="$(id -u)"

echo "==> Configuring HomeAuto systemd services for user '$USER_NAME' in '$CURRENT_DIR'..."

sudo tee /etc/systemd/system/homeauto.service > /dev/null <<EOF
[Unit]
Description=HomeAuto Platform Backend Hub
After=network.target sound.target bluetooth.target

[Service]
Type=simple
User=${USER_NAME}
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
Environment=XDG_RUNTIME_DIR=/run/user/${USER_UID}
Environment=PULSE_SERVER=unix:/run/user/${USER_UID}/pulse/native

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/homeauto-kiosk.service > /dev/null <<EOF
[Unit]
Description=HomeAuto 15" Touchscreen Chromium Kiosk Display
After=homeauto.service graphical.target
Wants=graphical.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${CURRENT_DIR}
Environment=DISPLAY=:0
Environment=WAYLAND_DISPLAY=wayland-0
Environment=XDG_RUNTIME_DIR=/run/user/${USER_UID}
Environment=XAUTHORITY=/home/${USER_NAME}/.Xauthority
ExecStart=${CURRENT_DIR}/kiosk.sh
Restart=always
RestartSec=3
TimeoutStopSec=5
KillMode=control-group
KillSignal=SIGTERM
SendSIGKILL=yes
FinalKillSignal=SIGKILL

[Install]
WantedBy=graphical.target
EOF

sudo systemctl daemon-reload
sudo systemctl restart homeauto.service
sudo systemctl restart homeauto-kiosk.service

echo "🎉 Services configured and restarted successfully!"
