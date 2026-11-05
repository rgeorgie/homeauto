#!/usr/bin/env bash
# ==========================================================
# HomeAuto 15" Touchscreen Kiosk Launcher for Raspberry Pi OS
# Compatible with X11, Wayland (Wayfire/Labwc), and LXDE
# ==========================================================

export DISPLAY="${DISPLAY:-:0}"
if [ -z "$XDG_RUNTIME_DIR" ]; then
  export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi
if [ -z "$WAYLAND_DISPLAY" ] && [ -e "$XDG_RUNTIME_DIR/wayland-0" ]; then
  export WAYLAND_DISPLAY="wayland-0"
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

# Clean up background helpers on exit
trap 'kill $(jobs -p) 2>/dev/null || true; exit 0' SIGTERM SIGINT EXIT

# Prevent Chromium session restore prompt hanging on unclean shutdown
PREFS_FILE="$HOME/.config/chromium/Default/Preferences"
if [ -f "$PREFS_FILE" ]; then
  sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/' "$PREFS_FILE" 2>/dev/null || true
  sed -i 's/"exited_cleanly":false/"exited_cleanly":true/' "$PREFS_FILE" 2>/dev/null || true
fi

# Wait for HomeAuto backend to be ready (up to 10s, fast poll)
echo "Waiting for HomeAuto server at http://127.0.0.1:8080..."
for i in {1..20}; do
  if curl -s --max-time 1 http://127.0.0.1:8080/api/status >/dev/null 2>&1; then
    echo "HomeAuto server is online!"
    break
  fi
  sleep 0.5
done

# Disable X11 screen sleep and screen savers (if on X11)
if command -v xset >/dev/null 2>&1; then
  xset s off 2>/dev/null || true
  xset -dpms 2>/dev/null || true
  xset s noblank 2>/dev/null || true
fi

# Hide mouse cursor on touchscreen
if command -v unclutter >/dev/null 2>&1; then
  pkill unclutter 2>/dev/null || true
  unclutter -idle 0.5 -root &
fi

# Launch Chromium in Fullscreen Touch Kiosk Mode
echo "Launching Chromium Touch Kiosk..."
exec $CHROMIUM_BIN \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-features=Translate,OptimizationHints,MediaRouter \
  --check-for-update-interval=31536000 \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --touch-events=enabled \
  --enable-features=OverlayScrollbar \
  --ozone-platform-hint=auto \
  --app=http://127.0.0.1:8080
