import logging
import asyncio
from typing import Dict, Any, List, Optional
import tinytuya

try:
    from tuya_connector import TuyaOpenAPI
    TUYA_CONNECTOR_AVAILABLE = True
except ImportError:
    TUYA_CONNECTOR_AVAILABLE = False

from backend.config import TuyaConfig, TuyaDeviceConfig

logger = logging.getLogger("HomeAuto.Tuya")

class TuyaManager:
    def __init__(self, config: TuyaConfig):
        self.config = config
        self.local_devices: Dict[str, tinytuya.OutletDevice] = {}
        self.device_states: Dict[str, Dict[str, Any]] = {}
        self.cloud_api: Optional[Any] = None
        self._init_cloud()
        self._init_local_devices()

    def _init_cloud(self):
        if self.config.cloud.access_id and self.config.cloud.access_secret and TUYA_CONNECTOR_AVAILABLE:
            try:
                self.cloud_api = TuyaOpenAPI(
                    endpoint=self.config.cloud.endpoint,
                    access_id=self.config.cloud.access_id,
                    access_secret=self.config.cloud.access_secret
                )
                self.cloud_api.connect()
                logger.info("Connected to Tuya Cloud API successfully.")
            except Exception as e:
                logger.error(f"Failed to connect to Tuya Cloud API: {e}")
                self.cloud_api = None

    def _init_local_devices(self):
        for dev_conf in self.config.devices:
            self.add_local_device(dev_conf)

    def add_local_device(self, dev_conf: TuyaDeviceConfig):
        try:
            if dev_conf.ip and dev_conf.local_key:
                if dev_conf.type in ["light", "bulb"]:
                    device = tinytuya.BulbDevice(
                        dev_id=dev_conf.id,
                        address=dev_conf.ip,
                        local_key=dev_conf.local_key,
                        version=dev_conf.version
                    )
                else:
                    device = tinytuya.OutletDevice(
                        dev_id=dev_conf.id,
                        address=dev_conf.ip,
                        local_key=dev_conf.local_key,
                        version=dev_conf.version
                    )
                device.set_socketPersistent(False)
                self.local_devices[dev_conf.id] = device
                
                # Pre-populate device state template
                self.device_states[dev_conf.id] = {
                    "id": dev_conf.id,
                    "name": dev_conf.name,
                    "type": dev_conf.type,
                    "room": dev_conf.room,
                    "online": False,
                    "is_on": False,
                    "brightness": 100,
                    "dps": {},
                    "error": None
                }
                logger.info(f"Registered local Tuya device: {dev_conf.name} ({dev_conf.id})")
        except Exception as e:
            logger.error(f"Error registering local Tuya device {dev_conf.name}: {e}")

    async def scan_local_network(self) -> List[Dict[str, Any]]:
        """Scans local subnet for Tuya broadcasts."""
        def _scan():
            try:
                devices = tinytuya.deviceScan(False, 5)
                return devices
            except Exception as e:
                logger.error(f"Error scanning local Tuya network: {e}")
                return []
        
        loop = asyncio.get_event_loop()
        raw_devices = await loop.run_in_executor(None, _scan)
        results = []
        if isinstance(raw_devices, dict):
            for ip, data in raw_devices.items():
                results.append({
                    "ip": ip,
                    "gwId": data.get("gwId"),
                    "version": data.get("version"),
                    "productKey": data.get("productKey")
                })
        return results

    async def fetch_cloud_devices(self) -> List[Dict[str, Any]]:
        """Fetches device list from Tuya Cloud."""
        if not self.cloud_api:
            return []
        
        def _fetch():
            try:
                uid = self.config.cloud.user_id
                if uid:
                    res = self.cloud_api.get(f"/v1.0/users/{uid}/devices")
                else:
                    res = self.cloud_api.get("/v1.0/devices")
                return res.get("result", []) if res.get("success") else []
            except Exception as e:
                logger.error(f"Error fetching devices from Tuya Cloud: {e}")
                return []

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)

    def _sync_poll_device(self, dev_id: str) -> Dict[str, Any]:
        dev = self.local_devices.get(dev_id)
        if not dev:
            return self.device_states.get(dev_id, {})
        
        try:
            status = dev.status()
            if status and "dps" in status:
                dps = status["dps"]
                is_on = False
                # Standard Tuya switch/light DPS is usually '1' or '20'
                if '1' in dps:
                    is_on = bool(dps['1'])
                elif '20' in dps:
                    is_on = bool(dps['20'])
                
                brightness = 100
                if '2' in dps:
                    brightness = int(dps['2'])
                elif '22' in dps:
                    brightness = int(dps['22'])

                state = self.device_states.get(dev_id, {})
                state.update({
                    "online": True,
                    "is_on": is_on,
                    "brightness": brightness,
                    "dps": dps,
                    "error": None
                })
                self.device_states[dev_id] = state
                return state
            else:
                if dev_id in self.device_states:
                    self.device_states[dev_id]["online"] = False
                    self.device_states[dev_id]["error"] = status.get("Error", "No response")
        except Exception as e:
            if dev_id in self.device_states:
                self.device_states[dev_id]["online"] = False
                self.device_states[dev_id]["error"] = str(e)
        
        return self.device_states.get(dev_id, {})

    async def get_all_states(self) -> List[Dict[str, Any]]:
        """Polls all registered devices and returns current states."""
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, self._sync_poll_device, dev_id)
            for dev_id in self.local_devices.keys()
        ]
        if tasks:
            await asyncio.gather(*tasks)
        return list(self.device_states.values())

    async def set_device_power(self, dev_id: str, is_on: bool) -> bool:
        """Toggles power for a device."""
        dev = self.local_devices.get(dev_id)
        if not dev:
            # Fallback to cloud if configured
            return await self._set_cloud_power(dev_id, is_on)

        def _set_power():
            try:
                if is_on:
                    dev.turn_on()
                else:
                    dev.turn_off()
                return True
            except Exception as e:
                logger.error(f"Error setting power for {dev_id}: {e}")
                return False

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, _set_power)
        if success:
            if dev_id in self.device_states:
                self.device_states[dev_id]["is_on"] = is_on
                self.device_states[dev_id]["online"] = True
        return success

    async def set_device_brightness(self, dev_id: str, brightness: int) -> bool:
        """Sets brightness (0-100 or 0-1000)."""
        dev = self.local_devices.get(dev_id)
        if not dev:
            return False

        def _set_bright():
            try:
                if isinstance(dev, tinytuya.BulbDevice):
                    dev.set_brightness_percentage(brightness)
                else:
                    # Generic DPS for dimmer/smart bulb
                    dev.set_value(22, brightness)
                return True
            except Exception as e:
                logger.error(f"Error setting brightness for {dev_id}: {e}")
                return False

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, _set_bright)
        if success:
            if dev_id in self.device_states:
                self.device_states[dev_id]["brightness"] = brightness
        return success

    async def _set_cloud_power(self, dev_id: str, is_on: bool) -> bool:
        if not self.cloud_api:
            return False
        
        def _send():
            try:
                commands = [{"code": "switch_1", "value": is_on}]
                res = self.cloud_api.post(f"/v1.0/devices/{dev_id}/commands", {"commands": commands})
                return bool(res.get("success"))
            except Exception as e:
                logger.error(f"Error sending cloud command to {dev_id}: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _send)
