import os
import logging
import asyncio
import subprocess
import shutil
import re
from typing import Dict, Any, List, Optional
from backend.config import BluetoothAudioConfig

logger = logging.getLogger("HomeAuto.Bluetooth")

class BluetoothAudioManager:
    def __init__(self, config: BluetoothAudioConfig):
        self.config = config
        self.is_connected = False
        self.current_device_name = self.config.device_name
        self.current_mac = self.config.target_mac
        self.volume = self.config.default_volume
        self.active_sink_name = ""
        self._reconnect_task: Optional[asyncio.Task] = None
        self._running = False

    def _get_audio_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        uid = os.getuid()
        home = os.path.expanduser("~")
        env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
        env["PULSE_SERVER"] = f"unix:/run/user/{uid}/pulse/native"
        env["PIPEWIRE_RUNTIME_DIR"] = f"/run/user/{uid}"
        if "DBUS_SESSION_BUS_ADDRESS" not in env:
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
        cookie = os.path.join(home, ".config", "pulse", "cookie")
        if os.path.exists(cookie):
            env["PULSE_COOKIE"] = cookie
        return env

    def start_background_service(self):
        self._running = True
        if self.config.enabled and self.config.auto_reconnect and self.config.target_mac:
            self._reconnect_task = asyncio.create_task(self._auto_reconnect_loop())
            logger.info("Started Bluetooth auto-reconnect supervisor.")

    def stop_background_service(self):
        self._running = False
        if self._reconnect_task:
            self._reconnect_task.cancel()

    def reload_config(self, config: BluetoothAudioConfig):
        self.config = config
        self.current_mac = self.config.target_mac
        self.current_device_name = self.config.device_name
        self.volume = self.config.default_volume
        logger.info("BluetoothAudioManager configuration reloaded.")

    async def _auto_reconnect_loop(self):
        while self._running:
            try:
                status = await self.check_connection_status()
                if not status.get("connected") and self.config.target_mac:
                    logger.info(f"Target Bluetooth speaker ({self.config.target_mac}) disconnected. Attempting reconnect...")
                    await self.connect_device(self.config.target_mac)
                elif status.get("connected") and self.config.target_mac:
                    # If connected but sink is not yet Bluetooth, ensure default sink is routed
                    if not self.active_sink_name or ("bluez" not in self.active_sink_name.lower()):
                        await self.switch_to_bluetooth_sink(self.config.target_mac)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Error in BT auto-reconnect loop: {e}")

            try:
                await asyncio.sleep(self.config.reconnect_interval_seconds)
            except asyncio.CancelledError:
                break

    async def check_connection_status(self) -> Dict[str, Any]:
        """Checks if the configured BT device or any BT audio sink is currently connected."""
        mac = self.config.target_mac
        connected = False
        device_name = self.config.device_name
        active_sink = ""

        def _exec():
            nonlocal connected, device_name, active_sink
            env = self._get_audio_env()
            try:
                if mac:
                    res = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True, timeout=1.5)
                    if "Connected: yes" in res.stdout:
                        connected = True
                        for line in res.stdout.splitlines():
                            if "Name:" in line:
                                device_name = line.split("Name:", 1)[1].strip()
                else:
                    res = subprocess.run(["bluetoothctl", "devices", "Connected"], capture_output=True, text=True, timeout=1.5)
                    lines = [l for l in res.stdout.splitlines() if l.strip()]
                    if lines:
                        connected = True
                        parts = lines[0].split(" ", 2)
                        if len(parts) >= 3:
                            device_name = parts[2]

                # Check default sink in pactl / PipeWire
                if shutil.which("pactl"):
                    info_res = subprocess.run(["pactl", "info"], capture_output=True, text=True, timeout=1.5, env=env)
                    for line in info_res.stdout.splitlines():
                        if "Default Sink:" in line:
                            active_sink = line.split("Default Sink:", 1)[1].strip()
            except Exception as e:
                logger.debug(f"Bluetoothctl check error: {e}")
                connected = False

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _exec)
        self.is_connected = connected
        self.current_device_name = device_name
        self.active_sink_name = active_sink
        return {
            "connected": connected,
            "mac": self.config.target_mac,
            "name": device_name,
            "volume": self.volume,
            "active_sink": active_sink,
            "is_bt_sink_active": "bluez" in active_sink.lower() if active_sink else False
        }

    async def get_audio_sinks(self) -> List[Dict[str, Any]]:
        """Lists all system audio output sinks (HDMI, Analog Headphone, Bluetooth Soundbar)."""
        def _get_sinks():
            sinks = []
            env = self._get_audio_env()
            if not shutil.which("pactl"):
                return sinks
            try:
                res = subprocess.run(["pactl", "list", "sinks"], capture_output=True, text=True, timeout=4, env=env)
                current_sink: Dict[str, Any] = {}
                for line in res.stdout.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("Sink #"):
                        if current_sink and "name" in current_sink:
                            sinks.append(current_sink)
                        current_sink = {"id": stripped.split("#")[1], "is_default": False}
                    elif stripped.startswith("Name:") and current_sink is not None:
                        current_sink["name"] = stripped.split("Name:", 1)[1].strip()
                        current_sink["is_bluetooth"] = "bluez" in current_sink["name"].lower()
                    elif stripped.startswith("Description:") and current_sink is not None:
                        current_sink["description"] = stripped.split("Description:", 1)[1].strip()
                if current_sink and "name" in current_sink:
                    sinks.append(current_sink)

                # Mark default
                for s in sinks:
                    if s.get("name") == self.active_sink_name:
                        s["is_default"] = True
            except Exception as e:
                logger.debug(f"Error querying audio sinks: {e}")
            return sinks

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_sinks)

    async def scan_devices(self) -> List[Dict[str, str]]:
        """Scans for nearby and paired Bluetooth devices."""
        def _scan():
            devices_map: Dict[str, str] = {}
            try:
                # 1. Trigger quick discovery scan (3s) to find pairing speakers
                subprocess.run(["bluetoothctl", "--timeout", "3", "scan", "on"], capture_output=True, text=True, timeout=5)
            except Exception:
                pass

            try:
                # 2. Get all discovered and paired devices
                res = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, timeout=3)
                for line in res.stdout.splitlines():
                    parts = line.strip().split(" ", 2)
                    if len(parts) >= 3 and parts[0] == "Device":
                        mac = parts[1].strip()
                        name = parts[2].strip()
                        if name and name != mac.replace(":", "-"):
                            devices_map[mac] = name
            except Exception as e:
                logger.error(f"Error scanning BT devices: {e}")
            return [{"mac": mac, "name": name} for mac, name in devices_map.items()]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _scan)

    async def connect_device(self, mac: str) -> bool:
        """Connects to a specific Bluetooth MAC and routes audio."""
        def _connect():
            try:
                # 1. Pair if required
                subprocess.run(["bluetoothctl", "pair", mac], capture_output=True, text=True, timeout=8)
                # 2. Trust device
                subprocess.run(["bluetoothctl", "trust", mac], capture_output=True, text=True, timeout=4)
                # 3. Connect A2DP profile
                res = subprocess.run(["bluetoothctl", "connect", mac], capture_output=True, text=True, timeout=12)
                connected = "Connection successful" in res.stdout or "Connected: yes" in res.stdout
                if not connected:
                    info_res = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True, timeout=3)
                    connected = "Connected: yes" in info_res.stdout
                return connected
            except Exception as e:
                logger.error(f"Error connecting to BT device {mac}: {e}")
                return False

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, _connect)
        if success:
            self.config.target_mac = mac
            self.is_connected = True
            # Read real device name
            try:
                info = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True, timeout=3)
                for line in info.stdout.splitlines():
                    if "Name:" in line:
                        self.current_device_name = line.split("Name:", 1)[1].strip()
                        self.config.device_name = self.current_device_name
            except Exception:
                pass

            logger.info(f"Successfully connected to Bluetooth device: {self.current_device_name} ({mac})")
            await asyncio.sleep(1.2)
            await self.switch_to_bluetooth_sink(mac)
        return success

    async def switch_to_bluetooth_sink(self, mac: str) -> bool:
        """Finds the Bluetooth audio sink and sets it as system default, migrating active streams and unmuting."""
        formatted_mac = mac.replace(":", "_").upper()
        formatted_mac_lower = mac.replace(":", "_").lower()

        def _switch():
            env = self._get_audio_env()
            try:
                if not shutil.which("pactl"):
                    return False

                # 1. Ensure high-quality A2DP profile on Bluetooth card
                for card_candidate in [f"bluez_card.{formatted_mac}", f"bluez_card.{formatted_mac_lower}"]:
                    subprocess.run(["pactl", "set-card-profile", card_candidate, "a2dp-sink"], capture_output=True, env=env)
                    subprocess.run(["pactl", "set-card-profile", card_candidate, "a2dp_sink"], capture_output=True, env=env)

                # 2. Find target Bluetooth sink
                res = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=3, env=env)
                target_sink = None
                for line in res.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        sink_name = parts[1]
                        if formatted_mac in sink_name or formatted_mac_lower in sink_name or "bluez_output" in sink_name or "bluez_sink" in sink_name:
                            target_sink = sink_name
                            break

                if target_sink:
                    self.active_sink_name = target_sink
                    # Unmute and set volume
                    subprocess.run(["pactl", "set-sink-mute", target_sink, "0"], capture_output=True, env=env)
                    subprocess.run(["pactl", "set-sink-volume", target_sink, f"{self.volume}%"], capture_output=True, env=env)
                    subprocess.run(["pactl", "set-default-sink", target_sink], capture_output=True, env=env)
                    
                    # 3. Migrate any currently playing streams (e.g. mpv, youtube audio)
                    inputs_res = subprocess.run(["pactl", "list", "short", "sink-inputs"], capture_output=True, text=True, timeout=3, env=env)
                    for in_line in inputs_res.stdout.splitlines():
                        in_parts = in_line.split()
                        if in_parts:
                            input_idx = in_parts[0]
                            subprocess.run(["pactl", "move-sink-input", input_idx, target_sink], capture_output=True, env=env)

                    logger.info(f"Successfully routed default audio sink to Bluetooth: {target_sink}")
                    return True
            except Exception as e:
                logger.debug(f"Error switching audio sink: {e}")
            return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _switch)

    def _generate_chime_wav(self, filepath: str = "/tmp/chime.wav") -> bool:
        """Generates a high quality 3.0s 4-note melodic chime WAV (C5-E5-G5-C6) to wake up soundbars."""
        try:
            import wave
            import struct
            import math
            sample_rate = 44100
            notes = [
                (0.0, 0.7, 523.25),  # C5
                (0.7, 1.4, 659.25),  # E5
                (1.4, 2.1, 783.99),  # G5
                (2.1, 3.0, 1046.50), # C6
            ]
            total_duration = 3.0
            n_samples = int(sample_rate * total_duration)
            with wave.open(filepath, "w") as wav_file:
                wav_file.setnchannels(2)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                for i in range(n_samples):
                    t = float(i) / sample_rate
                    freq = 523.25
                    env = 0.5
                    for start, end, f in notes:
                        if start <= t < end:
                            freq = f
                            note_t = (t - start) / (end - start)
                            env = math.sin(math.pi * note_t)
                            break
                    val = int(28000.0 * env * math.sin(2.0 * math.pi * freq * t))
                    packed = struct.pack("<hh", val, val)
                    wav_file.writeframesraw(packed)
            return True
        except Exception as e:
            logger.error(f"Error generating chime wave: {e}")
            return False

    async def play_test_tone(self) -> Dict[str, Any]:
        """Plays a pleasant test audio chime across active speaker/soundbar."""
        def _play():
            env = self._get_audio_env()
            target_sink = self.active_sink_name or "bluez_output.88_57_1D_F0_60_80.1"
            
            # Find exact sink name if available
            try:
                res = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=2, env=env)
                for line in res.stdout.splitlines():
                    if "bluez" in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            target_sink = parts[1]
                            break
            except Exception:
                pass

            # Unmute and ensure volume is loud enough for speaker amplifier (at least 75%)
            test_vol = max(75, self.volume)
            try:
                subprocess.run(["pactl", "set-sink-mute", target_sink, "0"], capture_output=True, env=env)
                subprocess.run(["pactl", "set-sink-volume", target_sink, f"{test_vol}%"], capture_output=True, env=env)
                subprocess.run(["pactl", "set-default-sink", target_sink], capture_output=True, env=env)
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], capture_output=True, env=env)
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{test_vol}%"], capture_output=True, env=env)
            except Exception:
                pass

            chime_path = "/tmp/chime.wav"
            self._generate_chime_wav(chime_path)
            errors = []

            logger.info(f"Playing test chime on soundbar (sink: {target_sink}, volume: {test_vol}%)")

            # 1. Try paplay with direct device targeting
            if shutil.which("paplay"):
                res = subprocess.run(["paplay", f"--device={target_sink}", chime_path], capture_output=True, text=True, timeout=6, env=env)
                if res.returncode == 0:
                    logger.info("Test chime succeeded via paplay")
                    return {"success": True, "method": "paplay", "sink": target_sink}
                if res.stderr:
                    errors.append(f"paplay: {res.stderr.strip()}")

            # 2. Try pw-play
            if shutil.which("pw-play"):
                res = subprocess.run(["pw-play", chime_path], capture_output=True, text=True, timeout=6, env=env)
                if res.returncode == 0:
                    logger.info("Test chime succeeded via pw-play")
                    return {"success": True, "method": "pw-play", "sink": target_sink}
                if res.stderr:
                    errors.append(f"pw-play: {res.stderr.strip()}")

            # 3. Try mpv
            if shutil.which("mpv"):
                res = subprocess.run(["mpv", "--no-video", "--ao=pulse,pipewire,alsa", f"--volume={test_vol}", chime_path], capture_output=True, text=True, timeout=6, env=env)
                if res.returncode == 0:
                    logger.info("Test chime succeeded via mpv")
                    return {"success": True, "method": "mpv", "sink": target_sink}
                if res.stderr:
                    errors.append(f"mpv: {res.stderr.strip()}")

            # 4. Try aplay
            if shutil.which("aplay"):
                res = subprocess.run(["aplay", "-D", "default", chime_path], capture_output=True, text=True, timeout=4, env=env)
                if res.returncode == 0:
                    logger.info("Test chime succeeded via aplay")
                    return {"success": True, "method": "aplay", "sink": target_sink}
                if res.stderr:
                    errors.append(f"aplay: {res.stderr.strip()}")

            logger.warning(f"Test chime failed: {'; '.join(errors)}")
            return {"success": False, "error": "; ".join(errors) if errors else "No working audio output device found"}

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _play)

    async def disconnect_device(self, mac: Optional[str] = None) -> bool:
        """Disconnects Bluetooth device."""
        target = mac or self.config.target_mac
        if not target:
            return False

        def _disconnect():
            try:
                res = subprocess.run(["bluetoothctl", "disconnect", target], capture_output=True, text=True, timeout=5)
                return "Successful disconnected" in res.stdout or res.returncode == 0
            except Exception as e:
                logger.error(f"Error disconnecting BT device {target}: {e}")
                return False

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, _disconnect)
        if success:
            self.is_connected = False
        return success

    async def set_volume(self, volume_percent: int) -> int:
        """Sets output volume (0-100) via pactl / PipeWire / ALSA."""
        vol = max(0, min(100, volume_percent))
        self.volume = vol

        def _set_vol():
            env = self._get_audio_env()
            try:
                if shutil.which("pactl"):
                    subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol}%"], capture_output=True, env=env)
                    return
                if shutil.which("amixer"):
                    subprocess.run(["amixer", "-M", "set", "Master", f"{vol}%"], capture_output=True)
            except Exception as e:
                logger.debug(f"Volume adjustment system call error: {e}")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _set_vol)
        return self.volume
