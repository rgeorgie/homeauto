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

    def reload_config(self, config: TuyaConfig):
        self.config = config
        self.local_devices.clear()
        self.device_states.clear()
        self._init_cloud()
        self._init_local_devices()
        logger.info("TuyaManager configuration reloaded.")

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
            # Always register device state template so it displays on the UI
            self.device_states[dev_conf.id] = {
                "id": dev_conf.id,
                "name": dev_conf.name,
                "type": dev_conf.type,
                "room": dev_conf.room,
                "ip": dev_conf.ip,
                "local_key": dev_conf.local_key,
                "online": False,
                "is_on": False,
                "brightness": 100,
                "dps": {},
                "error": None if (dev_conf.ip and dev_conf.local_key) else "Local key required"
            }

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
                logger.info(f"Registered local Tuya device: {dev_conf.name} ({dev_conf.id})")
            else:
                logger.info(f"Registered Tuya device placeholder (pending local key): {dev_conf.name} ({dev_conf.id})")
        except Exception as e:
            logger.error(f"Error registering local Tuya device {dev_conf.name}: {e}")

    async def scan_and_discover_devices(self) -> List[Dict[str, Any]]:
        """Scans local network and optionally queries cloud to return unified list of discovered devices."""
        def _perform_discovery():
            discovered = []
            cloud_device_map = {}

            # Step 1: Query Tuya Cloud via tinytuya.Cloud & TuyaOpenAPI if credentials exist
            if self.config.cloud.access_id and self.config.cloud.access_secret:
                try:
                    region = "eu"
                    if "tuyaus" in self.config.cloud.endpoint or "us" in self.config.cloud.endpoint:
                        region = "us"
                    elif "tuyacn" in self.config.cloud.endpoint or "cn" in self.config.cloud.endpoint:
                        region = "cn"
                    elif "tuyain" in self.config.cloud.endpoint or "in" in self.config.cloud.endpoint:
                        region = "in"

                    # Method A: TinyTuya Cloud
                    c = tinytuya.Cloud(
                        apiRegion=region,
                        apiKey=self.config.cloud.access_id,
                        apiSecret=self.config.cloud.access_secret
                    )
                    c_devices = c.getdevices()
                    if isinstance(c_devices, list):
                        for dev in c_devices:
                            dev_id = dev.get("id")
                            if dev_id:
                                cloud_device_map[dev_id] = dev
                    
                    # Method B: If still empty, try with TuyaOpenAPI
                    if not cloud_device_map and self.cloud_api:
                        res = self.cloud_api.get("/v1.0/devices")
                        if res and res.get("success") and "result" in res:
                            for dev in res.get("result", {}).get("devices", res.get("result", [])):
                                if isinstance(dev, dict) and dev.get("id"):
                                    cloud_device_map[dev["id"]] = dev

                    logger.info(f"Retrieved {len(cloud_device_map)} devices from Tuya Cloud API.")
                except Exception as e:
                    logger.warning(f"Cloud device fetch warning: {e}")

            # Step 2: Scan local network broadcasts
            try:
                local_raw = tinytuya.deviceScan(False, 6)
            except Exception as e:
                logger.error(f"Local Tuya scan error: {e}")
                local_raw = {}

            configured_ids = {d.id for d in self.config.devices}

            # Merge local devices
            if isinstance(local_raw, dict):
                for ip, data in local_raw.items():
                    dev_id = data.get("gwId") or data.get("id")
                    if not dev_id:
                        continue

                    cloud_info = cloud_device_map.get(dev_id, {})
                    category = cloud_info.get("category", "")
                    
                    # Deduce device type
                    dev_type = "switch"
                    if category in ["dj", "dd", "dc", "xdd"] or "light" in cloud_info.get("product_name", "").lower():
                        dev_type = "light"
                    elif category in ["cz", "pc"] or "socket" in cloud_info.get("product_name", "").lower() or "plug" in cloud_info.get("product_name", "").lower():
                        dev_type = "socket"
                    elif category in ["wk", "rs"] or "thermostat" in cloud_info.get("product_name", "").lower():
                        dev_type = "climate"
                    elif category in ["cg", "wsdcg"] or "sensor" in cloud_info.get("product_name", "").lower():
                        dev_type = "sensor"

                    name = cloud_info.get("name") or f"Tuya Device {dev_id[-4:]}"
                    local_key = cloud_info.get("key") or ""
                    version = float(data.get("version") or 3.3)

                    discovered.append({
                        "id": dev_id,
                        "name": name,
                        "ip": ip,
                        "local_key": local_key,
                        "version": version,
                        "type": dev_type,
                        "category": category or data.get("productKey", ""),
                        "product_name": cloud_info.get("product_name", "Local Tuya Device"),
                        "room": "Living Room",
                        "is_configured": dev_id in configured_ids
                    })

            # Add any cloud-only devices that weren't discovered by UDP broadcast
            seen_ids = {d["id"] for d in discovered}
            for dev_id, cdev in cloud_device_map.items():
                if dev_id not in seen_ids:
                    category = cdev.get("category", "")
                    dev_type = "switch"
                    if category in ["dj", "dd", "dc", "xdd"]:
                        dev_type = "light"
                    elif category in ["cz", "pc"]:
                        dev_type = "socket"
                    elif category in ["wk"]:
                        dev_type = "climate"

                    discovered.append({
                        "id": dev_id,
                        "name": cdev.get("name") or f"Device {dev_id[-4:]}",
                        "ip": cdev.get("ip") or "",
                        "local_key": cdev.get("key") or "",
                        "version": 3.3,
                        "type": dev_type,
                        "category": category,
                        "product_name": cdev.get("product_name", "Cloud Tuya Device"),
                        "room": "Default",
                        "is_configured": dev_id in configured_ids
                    })

            return discovered

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _perform_discovery)

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

    async def test_connection(self, dev_id: str, ip: str, local_key: str, version: float = 3.3) -> Dict[str, Any]:
        """Tests local communication with a device without saving."""
        def _test():
            try:
                device = tinytuya.OutletDevice(
                    dev_id=dev_id,
                    address=ip,
                    local_key=local_key,
                    version=version
                )
                device.set_socketPersistent(False)
                res = device.status()
                if res and "dps" in res:
                    return {"success": True, "dps": res["dps"]}
                else:
                    return {"success": False, "error": res.get("Error", "No status received")}
            except Exception as e:
                return {"success": False, "error": str(e)}

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _test)

    async def sync_all_cloud_keys(self) -> Dict[str, Any]:
        """Queries Tuya Cloud for each device to fetch and save local keys directly."""
        if not self.config.cloud.access_id or not self.config.cloud.access_secret:
            return {"success": False, "error": "Tuya Cloud Access ID and Secret are not set"}

        def _sync():
            region = "eu"
            if "tuyaus" in self.config.cloud.endpoint or "us" in self.config.cloud.endpoint:
                region = "us"
            elif "tuyacn" in self.config.cloud.endpoint or "cn" in self.config.cloud.endpoint:
                region = "cn"
            elif "tuyain" in self.config.cloud.endpoint or "in" in self.config.cloud.endpoint:
                region = "in"

            c = tinytuya.Cloud(
                apiRegion=region,
                apiKey=self.config.cloud.access_id,
                apiSecret=self.config.cloud.access_secret
            )
            
            # 1. Fetch devices list via TinyTuya
            cloud_devs = c.getdevices()
            cloud_key_map = {}

            if isinstance(cloud_devs, list):
                for d in cloud_devs:
                    dev_id = d.get("id")
                    key = d.get("key") or d.get("local_key")
                    if dev_id and key:
                        cloud_key_map[dev_id] = key

            # 2. If any configured devices are missing keys, query individual device details
            updated_count = 0
            for dev in self.config.devices:
                key = cloud_key_map.get(dev.id)
                if not key:
                    # Query individual device endpoint
                    try:
                        res = c.getconnectstatus(dev.id)
                        # Try c.cloudrequest
                        raw = c.cloudrequest(f"/v1.0/devices/{dev.id}")
                        if raw and "result" in raw and "local_key" in raw["result"]:
                            key = raw["result"]["local_key"]
                    except Exception as err:
                        logger.debug(f"Device {dev.id} key lookup error: {err}")

                if key:
                    dev.local_key = key
                    updated_count += 1

            return {
                "success": True,
                "total_cloud_found": len(cloud_devs) if isinstance(cloud_devs, list) else 0,
                "keys_updated": updated_count,
                "devices": [d.model_dump() for d in self.config.devices]
            }

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync)

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
