#!/usr/bin/env bash
# ==========================================================
# HomeAuto - Comprehensive Audio & Bluetooth Diagnostics
# ==========================================================

echo "=========================================================="
echo "🔊 HomeAuto Audio & Bluetooth Diagnostic Report"
echo "=========================================================="
echo "Host: $(hostname) | User: $(whoami) | Date: $(date)"
echo ""

echo "--- 1. Bluetooth Connection Status ---"
bluetoothctl info 88:57:1D:F0:60:80 2>&1 || bluetoothctl info
echo ""

echo "--- 2. PulseAudio / PipeWire Server Info ---"
pactl info 2>&1
echo ""

echo "--- 3. System Audio Sinks (Outputs) ---"
pactl list sinks 2>&1 | grep -E "Sink #|Name:|Description:|State:|Mute:|Volume:" || echo "No sinks found"
echo ""

echo "--- 4. Active Audio Streams (Sink Inputs) ---"
pactl list short sink-inputs 2>&1
echo ""

echo "--- 5. WirePlumber / PipeWire Status ---"
if command -v wpctl >/dev/null 2>&1; then
  wpctl status 2>&1
else
  echo "wpctl not found"
fi
echo ""

echo "--- 6. User Audio Services ---"
systemctl --user status pipewire pipewire-pulse wireplumber --no-pager 2>&1 | grep -E "●|Active:" || echo "PipeWire user services check completed"
echo ""

echo "--- 7. MPV Log (/tmp/mpv.log) ---"
if [ -f /tmp/mpv.log ]; then
  tail -n 25 /tmp/mpv.log
else
  echo "No /tmp/mpv.log file found"
fi
echo ""

echo "--- 8. Live Audio Playback Tests ---"
# Generate test chime
python3 -c '
import wave, struct, math
sample_rate = 44100
with wave.open("/tmp/diag_chime.wav", "w") as f:
    f.setnchannels(2); f.setsampwidth(2); f.setframerate(sample_rate)
    for i in range(sample_rate):
        val = int(18000.0 * math.sin(math.pi * i / sample_rate) * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
        f.writeframesraw(struct.pack("<hh", val, val))
'

echo "Test A: Trying 'paplay /tmp/diag_chime.wav'..."
paplay -v /tmp/diag_chime.wav 2>&1 || echo "paplay failed"

echo ""
echo "Test B: Trying 'pw-play /tmp/diag_chime.wav'..."
pw-play -v /tmp/diag_chime.wav 2>&1 || echo "pw-play failed"

echo ""
echo "Test C: Trying 'mpv --ao=pulse /tmp/diag_chime.wav'..."
mpv --no-video --ao=pulse /tmp/diag_chime.wav 2>&1 || echo "mpv failed"

echo ""
echo "=========================================================="
echo "Diagnostic Finished. Please copy and paste the output above."
echo "=========================================================="
