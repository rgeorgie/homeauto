#!/usr/bin/env bash
# ==========================================================
# HomeAuto 15" Touchscreen Kiosk Launcher for Raspberry Pi OS
# Compatible with X11, Wayland (Wayfire/Labwc), and LXDE
# ==========================================================

export DISPLAY="${DISPLAY:-:0}"
if [ -z "$XDG_RUNTIME_DIR" ]; then
  export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi

# Detect Chromium binary on Raspberry Pi OS
if command -v chromium-browser >/dev/null 2>&1; then
  CHROMIUM_BIN="chromium-browser"
elif command -v chromium >/dev/null 2>&1; then
  CHROMIUM_BIN="chromium"
else
  echo "Error: Chromium is not installed. Run: sudo apt install -y chromium-browser"
  exit 1
fi

# Wait for HomeAuto backend to be ready
echo "Waiting for HomeAuto server at http://localhost:8080..."
for i in {1..30}; do
  if curl -s http://localhost:8080/api/status >/dev/null 2>&1; then
    echo "HomeAuto server is online!"
    break
  fi
  sleep 1
done

# Disable X11 screen sleep and screen savers (if on X11)
if command -v xset >/dev/null 2>&1; then
  xset s off 2>/dev/null || true
  xset -dpms 2>/dev/null || true
  xset s noblank 2>/dev/null || true
fi

# Hide mouse cursor on touchscreen
if command -v unclutter >/dev/null 2>&1; then
  unclutter -idle 0.5 -root &
fi

# Launch Chromium in Fullscreen Touch Kiosk Mode
echo "Launching Chromium Touch Kiosk..."
exec $CHROMIUM_BIN \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --check-for-update-interval=31536000 \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --touch-events=enabled \
  --enable-features=OverlayScrollbar \
  --ozone-platform-hint=auto \
  --app=http://localhost:8080
