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

def resolve_tuya_device_type(category: str = "", product_name: str = "", name: str = "") -> str:
    """Accurately resolves device type based on Tuya Category code and names."""
    cat = (category or "").lower().strip()
    pname = (product_name or "").lower().strip()
    dname = (name or "").lower().strip()
    combined = f"{cat} {pname} {dname}"

    # 1. Pet Feeder / Pet Water Fountain / Cat Care
    if cat in ["cwf", "cwyq", "cwwsq", "cwsb", "pet"] or any(k in combined for k in ["pet", "feeder", "cat", "dog", "fountain", "kibble"]):
        return "pet_feeder"

    # 2. Climate / Thermostats / Heaters / Radiator TRVs
    if cat in ["wk", "wkf", "rs", "qn", "tc", "wkjsq"] or any(k in combined for k in ["thermostat", "heat", "heater", "climate", "trv", "valve", "underfloor"]):
        return "climate"

    # 3. Lights / Bulbs / Strips / Lamps
    if cat in ["dj", "dd", "dc", "xdd", "tyndj", "sbd", "tgq"] or any(k in combined for k in ["light", "bulb", "strip", "lamp", "led", "ceiling", "spotlight"]):
        return "light"

    # 4. Curtains / Blinds / Shutters / Garage
    if cat in ["cl", "clkg", "ckmkq"] or any(k in combined for k in ["curtain", "blind", "shutter", "roller", "garage"]):
        return "curtain"

    # 5. Sensors
    if cat in ["cg", "wsdcg", "mcs", "ywbj", "rqbj", "sj", "pir"] or any(k in combined for k in ["sensor", "detector", "motion", "door", "window", "leak", "smoke"]):
        return "sensor"

    # 6. Sockets / Plugs / Power Strips
    if cat in ["cz", "pc"] or any(k in combined for k in ["socket", "plug", "outlet", "power strip"]):
        return "socket"

    # 7. Fans / Air Purifiers / Humidifiers
    if cat in ["fs", "fsd", "jsq"] or any(k in combined for k in ["fan", "humidifier", "purifier"]):
        return "fan"

    return "switch"


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

                    uid = self.config.cloud.user_id.strip() if self.config.cloud.user_id else ""

                    c = tinytuya.Cloud(
                        apiRegion=region,
                        apiKey=self.config.cloud.access_id,
                        apiSecret=self.config.cloud.access_secret
                    )

                    # Method A: If UID provided, query user devices directly
                    if uid:
                        raw = c.cloudrequest(f"/v1.0/users/{uid}/devices")
                        if raw and raw.get("success") and "result" in raw:
                            for dev in raw.get("result", []):
                                if isinstance(dev, dict) and dev.get("id"):
                                    cloud_device_map[dev["id"]] = dev

                    # Method B: TinyTuya Cloud getdevices
                    if not cloud_device_map:
                        c_devices = c.getdevices()
                        if isinstance(c_devices, list):
                            for dev in c_devices:
                                if isinstance(dev, dict) and dev.get("id"):
                                    cloud_device_map[dev["id"]] = dev

                    # Method C: TuyaOpenAPI endpoints
                    if not cloud_device_map and self.cloud_api:
                        if uid:
                            res = self.cloud_api.get(f"/v1.0/users/{uid}/devices")
                            if res and res.get("success") and "result" in res:
                                for dev in res.get("result", []):
                                    if isinstance(dev, dict) and dev.get("id"):
                                        cloud_device_map[dev["id"]] = dev

                        if not cloud_device_map:
                            res = self.cloud_api.get("/v1.0/devices")
                            if res and res.get("success") and "result" in res:
                                devs = res.get("result", {}).get("devices", res.get("result", []))
                                if isinstance(devs, list):
                                    for dev in devs:
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
                    name = cloud_info.get("name") or f"Tuya Device {dev_id[-4:]}"
                    pname = cloud_info.get("product_name", "")
                    dev_type = resolve_tuya_device_type(category, pname, name)
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
                    name = cdev.get("name") or f"Device {dev_id[-4:]}"
                    pname = cdev.get("product_name", "")
                    dev_type = resolve_tuya_device_type(category, pname, name)

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
                if '2' in dps and isinstance(dps['2'], int) and dev_id in self.device_states and self.device_states[dev_id].get("type") in ["light", "bulb"]:
                    brightness = int(dps['2'])
                elif '22' in dps and isinstance(dps['22'], int):
                    brightness = int(dps['22'])

                # Thermostat / Heating DPS extraction
                target_temp = None
                current_temp = None
                mode = dps.get('4') or dps.get('2') or 'manual'

                # Target temp DPS candidates: '2', '16', '101', '24'
                for dps_key in ['2', '16', '101', '24', '103']:
                    if dps_key in dps and isinstance(dps[dps_key], (int, float)):
                        val = float(dps[dps_key])
                        if 5 <= val <= 45: # Standard Celsius range
                            target_temp = round(val, 1)
                            break
                        elif 50 <= val <= 450: # 10x scaled Celsius (e.g., 215 = 21.5°C)
                            target_temp = round(val / 10.0, 1)
                            break

                # Current temp DPS candidates: '3', '24', '102', '104', '28'
                for dps_key in ['3', '24', '102', '104', '28', '115']:
                    if dps_key in dps and isinstance(dps[dps_key], (int, float)):
                        val = float(dps[dps_key])
                        if 0 <= val <= 60:
                            current_temp = round(val, 1)
                            break
                        elif 0 <= val <= 600: # 10x scaled (e.g., 224 = 22.4°C)
                            current_temp = round(val / 10.0, 1)
                            break

                state = self.device_states.get(dev_id, {})
                state.update({
                    "online": True,
                    "is_on": is_on,
                    "brightness": brightness,
                    "current_temperature": current_temp if current_temp is not None else state.get("current_temperature", 21.0),
                    "target_temperature": target_temp if target_temp is not None else state.get("target_temperature", 22.0),
                    "mode": str(mode) if mode else "manual",
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
            # Ensure cloud_api is initialized
            if not self.cloud_api:
                self._init_cloud()

            uid = self.config.cloud.user_id.strip() if self.config.cloud.user_id else ""
            cloud_key_map = {}
            cloud_devices_list = []
            api_errors = []

            # Method 1: TuyaOpenAPI - User devices
            if self.cloud_api:
                try:
                    if uid:
                        logger.info(f"Querying Tuya Cloud for UID: {uid}")
                        res = self.cloud_api.get(f"/v1.0/users/{uid}/devices")
                        if res and res.get("success"):
                            r = res.get("result", [])
                            cloud_devices_list = r if isinstance(r, list) else r.get("devices", [])
                            logger.info(f"Tuya Cloud returned {len(cloud_devices_list)} devices for UID {uid}")
                        else:
                            err_msg = res.get("msg") if res else "No response"
                            api_errors.append(f"UID query: {err_msg}")
                            logger.warning(f"Tuya Cloud UID query warning: {res}")

                    if not cloud_devices_list:
                        res = self.cloud_api.get("/v1.0/devices")
                        if res and res.get("success"):
                            r = res.get("result", {})
                            cloud_devices_list = r if isinstance(r, list) else r.get("devices", [])
                except Exception as e:
                    logger.error(f"TuyaOpenAPI error: {e}")
                    api_errors.append(str(e))

            # Method 2: TinyTuya Cloud
            if not cloud_devices_list:
                try:
                    region = "eu"
                    if "tuyaus" in self.config.cloud.endpoint:
                        region = "us"
                    elif "tuyacn" in self.config.cloud.endpoint:
                        region = "cn"
                    elif "tuyain" in self.config.cloud.endpoint:
                        region = "in"

                    c = tinytuya.Cloud(
                        apiRegion=region,
                        apiKey=self.config.cloud.access_id,
                        apiSecret=self.config.cloud.access_secret
                    )
                    if uid:
                        raw = c.cloudrequest(f"/v1.0/users/{uid}/devices")
                        if raw and raw.get("success"):
                            cloud_devices_list = raw.get("result", [])
                    if not cloud_devices_list:
                        c_devs = c.getdevices()
                        if isinstance(c_devs, list) and len(c_devs) > 0:
                            cloud_devices_list = c_devs
                except Exception as e:
                    logger.error(f"TinyTuya Cloud error: {e}")

            # Populate map from any retrieved devices
            if isinstance(cloud_devices_list, list):
                for d in cloud_devices_list:
                    if isinstance(d, dict):
                        dev_id = d.get("id")
                        key = d.get("key") or d.get("local_key")
                        name = d.get("name")
                        if dev_id:
                            cloud_key_map[dev_id] = {
                                "key": key,
                                "name": name,
                                "category": d.get("category", ""),
                                "ip": d.get("ip", "")
                            }

            # Method 3: Direct per-device lookup via OpenAPI (/v1.0/devices/{id})
            updated_count = 0
            for dev in self.config.devices:
                info = cloud_key_map.get(dev.id, {})
                key = info.get("key")
                name = info.get("name")

                if not key and self.cloud_api:
                    try:
                        d_res = self.cloud_api.get(f"/v1.0/devices/{dev.id}")
                        if d_res and d_res.get("success") and "result" in d_res:
                            r = d_res["result"]
                            key = r.get("local_key") or r.get("key")
                            name = r.get("name") or dev.name
                            logger.info(f"Fetched key directly for {dev.id} ({name}): key_found={bool(key)}")
                    except Exception as err:
                        logger.debug(f"Direct device {dev.id} lookup error: {err}")

                if key:
                    dev.local_key = key
                    if name:
                        dev.name = name
                    updated_count += 1

            total_found = len(cloud_devices_list) if isinstance(cloud_devices_list, list) else 0

            return {
                "success": updated_count > 0 or total_found > 0,
                "total_cloud_found": total_found,
                "keys_updated": updated_count,
                "api_errors": api_errors,
                "devices": [d.model_dump() for d in self.config.devices]
            }

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync)

    async def set_device_temperature(self, dev_id: str, temperature: float) -> bool:
        """Sets target desired temperature for thermostat/heating device."""
        dev = self.local_devices.get(dev_id)
        if not dev:
            return False

        def _set_temp():
            try:
                state = self.device_states.get(dev_id, {})
                dps = state.get("dps", {})

                # Find which DPS key is used for target temperature
                target_key = None
                scale_10 = False

                for key in ['2', '16', '101', '24', '103']:
                    if key in dps and isinstance(dps[key], (int, float)):
                        target_key = int(key)
                        if dps[key] > 45: # 10x scale
                            scale_10 = True
                        break

                if target_key is None:
                    target_key = 2 # standard default for Tuya thermostat

                val = int(round(temperature * 10)) if scale_10 else int(round(temperature))
                dev.set_value(target_key, val)
                logger.info(f"Set target temperature for {dev_id} to {temperature}°C (DPS {target_key}={val})")
                return True
            except Exception as e:
                logger.error(f"Error setting temperature for {dev_id}: {e}")
                return False

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, _set_temp)
        if success and dev_id in self.device_states:
            self.device_states[dev_id]["target_temperature"] = round(temperature, 1)
        return success

    async def feed_pet(self, dev_id: str, portions: int = 1) -> bool:
        """Dispenses food for a smart pet feeder."""
        dev = self.local_devices.get(dev_id)
        if not dev:
            return False

        def _feed():
            try:
                state = self.device_states.get(dev_id, {})
                dps = state.get("dps", {})

                # Check which DPS controls manual feed
                feed_dps = None
                for key in ['3', '1', '101', '4', '2']:
                    if key in dps:
                        feed_dps = int(key)
                        break

                if feed_dps is None:
                    feed_dps = 3 # standard Tuya pet feeder manual_feed DPS

                dev.set_value(feed_dps, portions)
                logger.info(f"Dispensed {portions} portion(s) for pet feeder {dev_id} (DPS {feed_dps})")
                return True
            except Exception as e:
                logger.error(f"Error feeding pet on {dev_id}: {e}")
                return False

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, _feed)
        if success and dev_id in self.device_states:
            import datetime
            self.device_states[dev_id]["last_fed"] = datetime.datetime.now().strftime("%H:%M")
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
