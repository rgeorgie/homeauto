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
# The systemd unit always sets WAYLAND_DISPLAY; on an X11 session (e.g. Ubuntu x86) the socket doesn't exist
if [ -n "$WAYLAND_DISPLAY" ] && [ ! -e "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]; then
  unset WAYLAND_DISPLAY
fi
# X11 under a systemd user service needs the session's Xauthority (GDM on Ubuntu keeps it here)
if [ -z "$XAUTHORITY" ] && [ -f "$XDG_RUNTIME_DIR/gdm/Xauthority" ]; then
  export XAUTHORITY="$XDG_RUNTIME_DIR/gdm/Xauthority"
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
# (apt/Raspberry Pi OS profile, and the snap profile used by Ubuntu's chromium)
for PREFS_FILE in "$HOME/.config/chromium/Default/Preferences" "$HOME/snap/chromium/common/chromium/Default/Preferences"; do
  if [ -f "$PREFS_FILE" ]; then
    sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/' "$PREFS_FILE" 2>/dev/null || true
    sed -i 's/"exited_cleanly":false/"exited_cleanly":true/' "$PREFS_FILE" 2>/dev/null || true
  fi
done

# HomeAuto server URL: configurable via HOMEAUTO_SERVER env var or 1st arg (e.g. http://192.168.1.100:80)
# Defaults to local server port from config.yaml (default 80)
KIOSK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$KIOSK_DIR/.kiosk_env" ]; then
  # Load saved server URL and settings
  # shellcheck source=/dev/null
  . "$KIOSK_DIR/.kiosk_env"
fi
CUSTOM_SERVER="${HOMEAUTO_SERVER:-$1}"

# Platform tuning. The GPU flags and small JS heap suit a Raspberry Pi (ARM); on x86 (e.g. Fujitsu FUTRO)
# they are off by default. Override in .kiosk_env, e.g.:
#   export HOMEAUTO_GPU_FLAGS="--enable-gpu-rasterization --ignore-gpu-blocklist"
#   export HOMEAUTO_JS_HEAP_MB=384
#   export HOMEAUTO_CHROMIUM_ARGS="--disable-gpu"
case "$(uname -m)" in
  arm*|aarch64) DEFAULT_GPU_FLAGS="--enable-gpu-rasterization --ignore-gpu-blocklist"; DEFAULT_HEAP=192 ;;
  *)            DEFAULT_GPU_FLAGS="";                                                  DEFAULT_HEAP=384 ;;
esac
GPU_FLAGS="${HOMEAUTO_GPU_FLAGS-$DEFAULT_GPU_FLAGS}"
JS_HEAP_MB="${HOMEAUTO_JS_HEAP_MB:-$DEFAULT_HEAP}"

if [ -n "$CUSTOM_SERVER" ]; then
  BASE_URL="${CUSTOM_SERVER%/}"
else
  PORT="$(awk '/^server:/{f=1;next} f&&/^[^ #]/{f=0} f&&/port:/{print $2; exit}' "$KIOSK_DIR/config.yaml" 2>/dev/null)"
  PORT="${PORT:-80}"
  BASE_URL="http://127.0.0.1:${PORT}"
fi

# Wait for HomeAuto backend to be ready (up to 20s, fast poll)
echo "Waiting for HomeAuto server at ${BASE_URL}..."
for i in {1..40}; do
  if curl -s --max-time 1 "${BASE_URL}/api/status" >/dev/null 2>&1; then
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
  --autoplay-policy=no-user-gesture-required \
  --disable-session-crashed-bubble \
  --disable-features=Translate,OptimizationHints,MediaRouter,LocalNetworkAccessChecks,BlockInsecurePrivateNetworkRequests \
  --check-for-update-interval=31536000 \
  --password-store=basic \
  --disable-renderer-accessibility \
  --disable-background-networking \
  --disable-component-update \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --touch-events=enabled \
  --disable-dev-shm-usage \
  $GPU_FLAGS \
  --renderer-process-limit=1 \
  --disable-sync \
  --disable-extensions \
  --no-first-run \
  --js-flags="--max-old-space-size=${JS_HEAP_MB}" \
  --disk-cache-size=1 \
  --media-cache-size=1 \
  --enable-features=OverlayScrollbar,TouchEvents \
  --ozone-platform-hint=auto \
  --log-level=3 \
  $HOMEAUTO_CHROMIUM_ARGS \
  --app="${BASE_URL}/?kiosk=1"
