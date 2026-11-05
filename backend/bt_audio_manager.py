import logging
import asyncio
import subprocess
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
        self._reconnect_task: Optional[asyncio.Task] = None
        self._running = False

    def start_background_service(self):
        self._running = True
        if self.config.enabled and self.config.auto_reconnect and self.config.target_mac:
            self._reconnect_task = asyncio.create_task(self._auto_reconnect_loop())
            logger.info("Started Bluetooth auto-reconnect supervisor.")

    def stop_background_service(self):
        self._running = False
        if self._reconnect_task:
            self._reconnect_task.cancel()

    async def _auto_reconnect_loop(self):
        while self._running:
            try:
                status = await self.check_connection_status()
                if not status.get("connected") and self.config.target_mac:
                    logger.info(f"Target Bluetooth speaker ({self.config.target_mac}) not connected. Attempting connect...")
                    await self.connect_device(self.config.target_mac)
            except Exception as e:
                logger.error(f"Error in BT auto-reconnect loop: {e}")
            await asyncio.sleep(self.config.reconnect_interval_seconds)

    async def check_connection_status(self) -> Dict[str, Any]:
        """Checks if the configured BT device or any BT audio sink is currently connected."""
        mac = self.config.target_mac
        connected = False
        device_name = self.config.device_name

        def _exec():
            nonlocal connected, device_name
            try:
                if mac:
                    res = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True, timeout=5)
                    if "Connected: yes" in res.stdout:
                        connected = True
                        for line in res.stdout.splitlines():
                            if "Name:" in line:
                                device_name = line.split("Name:", 1)[1].strip()
                else:
                    # Check paired and connected devices
                    res = subprocess.run(["bluetoothctl", "devices", "Connected"], capture_output=True, text=True, timeout=5)
                    lines = [l for l in res.stdout.splitlines() if l.strip()]
                    if lines:
                        connected = True
                        parts = lines[0].split(" ", 2)
                        if len(parts) >= 3:
                            device_name = parts[2]
            except Exception as e:
                logger.debug(f"Bluetoothctl check error (expected if mock/mac not present): {e}")
                connected = False

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _exec)
        self.is_connected = connected
        self.current_device_name = device_name
        return {
            "connected": connected,
            "mac": self.config.target_mac,
            "name": device_name,
            "volume": self.volume
        }

    async def scan_devices(self) -> List[Dict[str, str]]:
        """Scans for nearby Bluetooth devices."""
        def _scan():
            devices = []
            try:
                # Get paired / cached devices first
                res = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, timeout=5)
                for line in res.stdout.splitlines():
                    parts = line.strip().split(" ", 2)
                    if len(parts) >= 3 and parts[0] == "Device":
                        devices.append({"mac": parts[1], "name": parts[2]})
            except Exception as e:
                logger.error(f"Error scanning BT devices: {e}")
            return devices

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _scan)

    async def connect_device(self, mac: str) -> bool:
        """Connects to a specific Bluetooth MAC."""
        def _connect():
            try:
                subprocess.run(["bluetoothctl", "trust", mac], capture_output=True, timeout=5)
                res = subprocess.run(["bluetoothctl", "connect", mac], capture_output=True, text=True, timeout=10)
                return "Connection successful" in res.stdout or "Connected: yes" in res.stdout
            except Exception as e:
                logger.error(f"Error connecting to BT device {mac}: {e}")
                return False

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, _connect)
        if success:
            self.config.target_mac = mac
            self.is_connected = True
            logger.info(f"Successfully connected to Bluetooth device: {mac}")
        return success

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
        """Sets output volume (0-100) via pactl / wpctl / amixer."""
        vol = max(0, min(100, volume_percent))
        self.volume = vol

        def _set_vol():
            try:
                # Try pactl (PulseAudio / PipeWire Pulse)
                pactl_res = subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol}%"], capture_output=True)
                if pactl_res.returncode == 0:
                    return
                # Try amixer fallback
                subprocess.run(["amixer", "-M", "set", "Master", f"{vol}%"], capture_output=True)
            except Exception as e:
                logger.debug(f"Volume adjustment system call error: {e}")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _set_vol)
        return self.volume
