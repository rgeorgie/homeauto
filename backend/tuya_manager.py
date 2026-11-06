import re
import time
import datetime
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

# Min seconds between Tuya Cloud status queries per device (protects the cloud API quota)
CLOUD_POLL_INTERVAL_SECONDS = 60
# Pet feeder feeding-log refresh interval, and the Tuya log codes that record a dispense (in order of preference)
FEEDING_REFRESH_SECONDS = 300
FEED_LOG_CODES = ("feed_report", "manual_feed", "feed_state")

def resolve_tuya_device_type(category: str = "", product_name: str = "", name: str = "") -> str:
    """Resolves device type from the Tuya category code (authoritative) and then product/device names."""
    cat = (category or "").lower().strip()
    words = re.findall(r"[a-z0-9]+", f"{product_name or ''} {name or ''}".lower())

    def has(keys) -> bool:
        # Short keys must match a whole word (so "cat" does not match "indicator"); longer keys match word prefixes.
        for k in keys:
            for w in words:
                if (len(k) <= 3 and w in (k, k + "s")) or (len(k) > 3 and w.startswith(k)):
                    return True
        return False

    pet_cats = ["cwf", "cwyq", "cwwsq", "cwsb", "pet", "cw", "cww"]
    climate_cats = ["wk", "wkf", "rs", "qn", "tc", "wkjsq"]
    light_cats = ["dj", "dd", "dc", "xdd", "tyndj", "sbd", "tgq"]
    curtain_cats = ["cl", "clkg", "ckmkq"]
    sensor_cats = ["cg", "wsdcg", "mcs", "ywbj", "rqbj", "sj", "pir", "hjjcy", "zd", "sgbj", "ldcg", "wnykq", "co2bj", "pm25", "jwbj"]
    socket_cats = ["cz", "pc"]
    fan_cats = ["fs", "fsd", "jsq"]

    # Category code from Tuya Cloud is authoritative when present
    if cat in pet_cats:
        return "pet_feeder"
    if cat in climate_cats:
        return "climate"
    if cat in light_cats:
        return "light"
    if cat in curtain_cats:
        return "curtain"
    if cat in sensor_cats:
        return "sensor"
    if cat in socket_cats:
        return "socket"
    if cat in fan_cats:
        return "fan"

    # Fall back to names when category is unknown
    if has(["pet", "feeder", "feed", "cat", "dog", "fountain", "kibble", "meal", "treat", "portion", "dispenser", "waterer", "snack", "litter"]):
        return "pet_feeder"
    if has(["thermostat", "heat", "climate", "trv", "valve", "underfloor", "radiator", "boiler"]):
        return "climate"
    if has(["sensor", "detector", "motion", "leak", "smoke"]):
        return "sensor"
    if "strip" in words and any(w in words for w in ("power", "socket", "sockets", "outlet", "outlets", "plug", "extension", "surge")):
        return "socket"
    if has(["light", "bulb", "strip", "lamp", "led", "ceiling", "spotlight"]):
        return "light"
    if has(["curtain", "blind", "shutter", "roller", "garage"]):
        return "curtain"
    if has(["socket", "plug", "outlet"]):
        return "socket"
    if has(["fan", "humidifier", "purifier"]):
        return "fan"

    return "switch"


def extract_tuya_climate_data(dps: Dict[str, Any], dev_type: str = "climate") -> Dict[str, Any]:
    """
    Extracts target temperature, current temperature, humidity, mode, battery, and heating status
    from Tuya DPS data across standard Tuya, Moes, Avatto, Beca, Floureon, TRVs, and sensors.
    """
    def _parse_temp(val: Any) -> Optional[float]:
        if val is None or isinstance(val, bool):
            return None
        if isinstance(val, (int, float)):
            num = float(val)
            # 1. Standard 1x Celsius: 0.0 <= num <= 45.0
            if 0.0 <= num <= 45.0:
                return round(num, 1)
            # 2. 10x scaled Celsius: 45.0 < num <= 500.0 (e.g. 215 = 21.5°C)
            elif 45.0 < num <= 500.0:
                return round(num / 10.0, 1)
            # 3. 100x scaled Celsius: 500.0 < num <= 5000.0 (e.g. 2150 = 21.5°C)
            elif 500.0 < num <= 5000.0:
                return round(num / 100.0, 1)
        return None

    def _get_scale(raw_val: Any) -> int:
        if raw_val is not None and isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool):
            num = float(raw_val)
            if num > 500:
                return 100
            elif num > 45:
                return 10
        return 1

    target_temp = None
    target_dps_key = None
    target_scale = 10

    current_temp = None
    current_dps_key = None

    humidity = None
    battery = None
    mode = None

    # --- Mode extraction ---
    for mode_key in ['2', '4', '104', '116', '118']:
        if mode_key in dps:
            m_val = dps[mode_key]
            if isinstance(m_val, str):
                mode = m_val
                break

    is_sensor = '1' in dps and isinstance(dps['1'], (int, float)) and not isinstance(dps['1'], bool) and ('2' in dps or '3' in dps) and not ('16' in dps or '101' in dps or '103' in dps)

    if is_sensor:
        # Schema: Temperature Sensor (Category wsdcg, th01, cg)
        # DP 1 = current temperature, DP 2 = humidity, DP 3 = battery
        parsed_cur = _parse_temp(dps['1'])
        if parsed_cur is not None:
            current_temp = parsed_cur
            current_dps_key = '1'
        if '2' in dps and isinstance(dps['2'], (int, float)) and not isinstance(dps['2'], bool):
            h_val = int(dps['2'])
            humidity = h_val if 0 <= h_val <= 100 else int(round(h_val / 10.0))
        if '3' in dps and isinstance(dps['3'], (int, float)) and not isinstance(dps['3'], bool):
            b_val = int(dps['3'])
            battery = b_val if 0 <= b_val <= 100 else int(round(b_val / 10.0))

    if not is_sensor:
        # --- Schema A: Standard Tuya (Category wk / wkf / rs / qn) ---
        # DP 16 = temp_set, DP 24 = temp_current
        if '16' in dps and not isinstance(dps['16'], bool):
            parsed = _parse_temp(dps['16'])
            if parsed is not None:
                target_temp = parsed
                target_dps_key = '16'
                target_scale = _get_scale(dps['16'])

        if '24' in dps and not isinstance(dps['24'], bool):
            parsed = _parse_temp(dps['24'])
            if parsed is not None:
                current_temp = parsed
                current_dps_key = '24'

        # --- Schema B: Moes / Avatto / WiFi Underfloor heating ---
        # DP 101 = temp_set, DP 102 = temp_current
        if target_temp is None and '101' in dps and not isinstance(dps['101'], bool):
            parsed = _parse_temp(dps['101'])
            if parsed is not None:
                target_temp = parsed
                target_dps_key = '101'
                target_scale = _get_scale(dps['101'])

        if current_temp is None and '102' in dps and not isinstance(dps['102'], bool):
            parsed = _parse_temp(dps['102'])
            if parsed is not None:
                current_temp = parsed
                current_dps_key = '102'

        # --- Schema C: Tuya TRV / Radiator valves (HY368 / TS0601 / Sea801 / TV01) ---
        # DP 103 = temp_set, DP 104 = temp_current (or DP 24 target, DP 28 current)
        if target_temp is None and '103' in dps and not isinstance(dps['103'], bool):
            parsed = _parse_temp(dps['103'])
            if parsed is not None:
                target_temp = parsed
                target_dps_key = '103'
                target_scale = _get_scale(dps['103'])

        if current_temp is None and '104' in dps and not isinstance(dps['104'], bool):
            parsed = _parse_temp(dps['104'])
            if parsed is not None:
                current_temp = parsed
                current_dps_key = '104'

        if current_temp is None and '28' in dps and not isinstance(dps['28'], bool):
            parsed = _parse_temp(dps['28'])
            if parsed is not None:
                current_temp = parsed
                current_dps_key = '28'

        # --- Schema D: Floor heating with mode on DP 2 ---
        # DP 4 = temp_set (int), DP 5 = temp_current (int)
        if target_temp is None and '4' in dps and isinstance(dps['4'], (int, float)) and not isinstance(dps['4'], bool):
            parsed = _parse_temp(dps['4'])
            if parsed is not None:
                target_temp = parsed
                target_dps_key = '4'
                target_scale = _get_scale(dps['4'])

        if current_temp is None and '5' in dps and isinstance(dps['5'], (int, float)) and not isinstance(dps['5'], bool):
            parsed = _parse_temp(dps['5'])
            if parsed is not None:
                current_temp = parsed
                current_dps_key = '5'

        # --- Schema E: Beca BHT-002 / BHT-6000 / Floureon ---
        # DP 2 = temp_set (int), DP 3 = temp_current (int)
        if target_temp is None and '2' in dps and isinstance(dps['2'], (int, float)) and not isinstance(dps['2'], bool):
            parsed = _parse_temp(dps['2'])
            if parsed is not None:
                target_temp = parsed
                target_dps_key = '2'
                target_scale = _get_scale(dps['2'])

        if current_temp is None and '3' in dps and isinstance(dps['3'], (int, float)) and not isinstance(dps['3'], bool):
            parsed = _parse_temp(dps['3'])
            if parsed is not None:
                current_temp = parsed
                current_dps_key = '3'

        # --- Generic Fallback Scan for Target Temperature ---
        if target_temp is None:
            for k in ['16', '101', '103', '105', '106', '4', '2', '8', '18', '19', '26', '30', '40']:
                if k in dps and not isinstance(dps[k], bool):
                    parsed = _parse_temp(dps[k])
                    if parsed is not None:
                        target_temp = parsed
                        target_dps_key = k
                        target_scale = _get_scale(dps[k])
                        break

        # --- Generic Fallback Scan for Current Temperature ---
        if current_temp is None:
            for k in ['24', '102', '104', '3', '5', '28', '115', '114', '116', '107', '109', '18', '19', '20', '1']:
                if k in dps and k != target_dps_key and not isinstance(dps[k], bool):
                    parsed = _parse_temp(dps[k])
                    if parsed is not None:
                        current_temp = parsed
                        current_dps_key = k
                        break

        # --- Humidity extraction ---
        if humidity is None:
            for h_key in ['2', '102', '114', '115', '116', '19', '21']:
                if h_key in dps and h_key != target_dps_key and h_key != current_dps_key:
                    val = dps[h_key]
                    if isinstance(val, (int, float)) and not isinstance(val, bool):
                        h_num = int(val)
                        if 0 <= h_num <= 100:
                            humidity = h_num
                            break
                        elif 100 < h_num <= 1000:
                            humidity = int(round(h_num / 10.0))
                            break

        # --- Battery extraction ---
        if battery is None:
            for b_key in ['3', '14', '15', '105', '115', '116']:
                if b_key in dps and b_key != target_dps_key and b_key != current_dps_key and b_key != '2':
                    val = dps[b_key]
                    if isinstance(val, (int, float)) and not isinstance(val, bool):
                        b_num = int(val)
                        if 0 <= b_num <= 100:
                            battery = b_num
                            break

    return {
        "target_temperature": target_temp,
        "target_dps_key": target_dps_key,
        "target_scale": target_scale,
        "current_temperature": current_temp,
        "current_dps_key": current_dps_key,
        "humidity": humidity,
        "battery": battery,
        "mode": mode or "manual"
    }


BATTERY_STATE_LABELS = {"low": "Low", "middle": "Medium", "high": "High"}
MAX_SWITCH_CHANNELS = 8


def extract_motion_data(dps: Dict[str, Any], category: str = "") -> Optional[Dict[str, Any]]:
    """
    Detects a PIR motion detector from local DPS and extracts its state and battery.
    Tuya 'pir' category: DP 1 pir = "pir" (motion) / "none", DP 3 battery_state = low/middle/high, DP 4 battery_percentage.
    Returns None when the DPS do not look like a motion detector.
    """
    pir = dps.get('1')
    looks_like_pir = isinstance(pir, str) and pir.lower() in ("pir", "none")
    if not looks_like_pir and (category or "").lower() != "pir":
        return None

    battery = None
    for key in ('4', '3'):
        val = dps.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and 0 <= val <= 100:
            battery = int(val)
            break
    battery_state = dps.get('3') if isinstance(dps.get('3'), str) else None
    return {
        "motion": (pir.lower() == "pir") if isinstance(pir, str) else None,
        "battery": battery,
        "battery_state": BATTERY_STATE_LABELS.get((battery_state or "").lower()),
    }


def extract_switch_channels(values: Dict[str, Any], cloud: bool = False) -> List[Dict[str, Any]]:
    """
    Returns [{index, is_on, label}] for every boolean on/off output of a multi-line device (power strip, 2-3 gang switch),
    or [] when there are fewer than 2. `index` is the Tuya DP number. Local DPS use keys '1'..'8';
    Tuya Cloud uses codes switch_1..switch_8 and switch_usb1..switch_usb4 (standard spec: USB outputs are DP 7+).
    The lines need not be consecutive (strips often put the USB block on DP 7).
    """
    channels = []
    for i in range(1, MAX_SWITCH_CHANNELS + 1):
        val = values.get(f"switch_{i}" if cloud else str(i))
        if isinstance(val, bool):
            channels.append({"index": i, "is_on": val, "label": f"Line {i}"})
    if cloud:
        for j in range(1, 5):
            val = values.get(f"switch_usb{j}")
            if isinstance(val, bool):
                channels.append({"index": 6 + j, "is_on": val, "label": f"USB {j}"})
    return channels if len(channels) >= 2 else []


class TuyaManager:
    def __init__(self, config: TuyaConfig):
        self.config = config
        self.local_devices: Dict[str, tinytuya.OutletDevice] = {}
        self.device_states: Dict[str, Dict[str, Any]] = {}
        self.cloud_api: Optional[Any] = None
        self._running: bool = False
        self.location_errors: List[str] = []
        self._feed_log: Dict[str, List[tuple]] = {}  # dev_id -> [(timestamp, portions)] dispensed through HomeAuto
        self._feeding_fetched_at: Dict[str, float] = {}
        self._poll_task: Optional[asyncio.Task] = None
        self._init_cloud()
        self._init_local_devices()

    def start_background_service(self):
        self._running = True
        if not self._poll_task or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._background_poll_loop())
            logger.info("Started Tuya background device polling worker.")

    def stop_background_service(self):
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()

    def reload_config(self, config: TuyaConfig):
        self.config = config
        self.local_devices.clear()
        self.device_states.clear()
        self._init_cloud()
        self._init_local_devices()
        logger.info("TuyaManager configuration reloaded.")

    async def _background_poll_loop(self):
        sem = asyncio.Semaphore(4)
        loop = asyncio.get_event_loop()

        async def _poll_one(dev_id):
            async with sem:
                try:
                    await loop.run_in_executor(None, self._sync_poll_device, dev_id)
                    await loop.run_in_executor(None, self._refresh_feeding_records, dev_id)
                except Exception as e:
                    logger.debug(f"Poll error for {dev_id}: {e}")

        while self._running:
            try:
                dev_ids = list(self.device_states.keys()) if self.cloud_api else list(self.local_devices.keys())
                if dev_ids:
                    tasks = [_poll_one(did) for did in dev_ids]
                    await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Tuya poll loop exception: {e}")

            try:
                await asyncio.sleep(8.0)
            except asyncio.CancelledError:
                break

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
                "category": dev_conf.category,
                "room": dev_conf.room,
                "home": dev_conf.home,
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
                device.set_socketTimeout(3.0)
                device.set_socketRetryLimit(2)
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

            # Home / room names from the Tuya Cloud (needs User ID); best effort
            try:
                loc_map = self._fetch_home_room_map(self.config.cloud.user_id.strip() if self.config.cloud.user_id else "", list(cloud_device_map.values()))
            except Exception as e:
                logger.info(f"Home/room lookup failed: {e}")
                loc_map = {}

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
                        "home": loc_map.get(dev_id, {}).get("home", ""),
                        "room": loc_map.get(dev_id, {}).get("room", ""),
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
                        "home": loc_map.get(dev_id, {}).get("home", ""),
                        "room": loc_map.get(dev_id, {}).get("room", ""),
                        "is_configured": dev_id in configured_ids
                    })

            return discovered

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _perform_discovery)

    def _sync_poll_device(self, dev_id: str) -> Dict[str, Any]:
        dev = self.local_devices.get(dev_id)
        local_error = "Local key required" if not dev else None

        if dev:
            try:
                status = dev.status()
                if status and "dps" in status:
                    return self._apply_dps(dev_id, status["dps"], "local")
                local_error = (status or {}).get("Error") or "No response"
            except Exception as e:
                local_error = str(e)

        # Local access failed or unavailable: fall back to Tuya Cloud (rate limited to protect API quota)
        cloud_state = self._poll_cloud_device(dev_id)
        if cloud_state:
            return cloud_state

        if dev_id in self.device_states:
            st = self.device_states[dev_id]
            if st.get("online", False) or st.get("error") != local_error:
                logger.warning(f"Tuya device '{st.get('name')}' ({dev_id}) at {st.get('ip')} is offline: {local_error}")
            st["online"] = False
            st["error"] = local_error
        return self.device_states.get(dev_id, {})

    def _apply_dps(self, dev_id: str, dps: Dict[str, Any], source: str) -> Dict[str, Any]:
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

        # Thermostat / Heating / Climate DPS extraction
        state = self.device_states.get(dev_id, {})
        climate_data = extract_tuya_climate_data(dps, dev_type=state.get("type", "climate"))

        # Motion detector (state + battery only) and multi-line switches (one entry per line)
        motion = extract_motion_data(dps, state.get("category", ""))
        if motion:
            if motion["battery"] is not None:
                climate_data["battery"] = motion["battery"]
            climate_data["current_temperature"] = climate_data["humidity"] = None
            state["type"] = "sensor"
        state["motion"] = motion["motion"] if motion else None
        state["battery_state"] = motion["battery_state"] if motion else None
        state["is_motion_sensor"] = bool(motion)
        if not motion and (state.get("category") or "").lower() == "mcs" and isinstance(dps.get("1"), bool):
            state["contact_open"] = dps["1"]
            state["type"] = "sensor"
            for key in ("3", "2"):
                val = dps.get(key)
                if isinstance(val, int) and not isinstance(val, bool) and 0 <= val <= 100:
                    climate_data["battery"] = val
                    break
            climate_data["current_temperature"] = climate_data["humidity"] = None
        channels = []
        if state.get("type") in ("switch", "socket"):
            channels = extract_switch_channels(dps)
        state["channels"] = channels

        state.update({
            "online": True,
            "is_on": is_on,
            "brightness": brightness,
            "current_temperature": climate_data["current_temperature"] if climate_data["current_temperature"] is not None else state.get("current_temperature"),
            "target_temperature": climate_data["target_temperature"] if climate_data["target_temperature"] is not None else state.get("target_temperature"),
            "target_dps_key": climate_data["target_dps_key"] or state.get("target_dps_key"),
            "target_scale": climate_data["target_scale"] or state.get("target_scale", 10),
            "humidity": climate_data["humidity"] if climate_data["humidity"] is not None else state.get("humidity"),
            "battery": climate_data["battery"] if climate_data["battery"] is not None else state.get("battery"),
            "mode": climate_data["mode"] or state.get("mode", "manual"),
            "dps": dps,
            "source": source,
            "error": None
        })
        self.device_states[dev_id] = state
        return state

    def _poll_cloud_device(self, dev_id: str) -> Optional[Dict[str, Any]]:
        """Reads device status from Tuya Cloud (code/value pairs). Returns None if unavailable."""
        if not self.cloud_api or dev_id not in self.device_states:
            return None
        state = self.device_states[dev_id]
        now = time.time()
        if now - state.get("_cloud_polled_at", 0) < CLOUD_POLL_INTERVAL_SECONDS:
            return state if state.get("source") == "cloud" and state.get("online") else None
        state["_cloud_polled_at"] = now

        try:
            # Cloud status returns last-known values even for offline devices, so check the real online flag first
            info = self.cloud_api.get(f"/v1.0/devices/{dev_id}")
            if info and info.get("success") and isinstance(info.get("result"), dict) and info["result"].get("online") is False:
                state.update({"online": False, "source": "cloud", "error": "Offline in Tuya Cloud (device not connected)"})
                return state
            res = self.cloud_api.get(f"/v1.0/devices/{dev_id}/status")
            if not (res and res.get("success") and isinstance(res.get("result"), list)):
                logger.debug(f"Cloud status for {dev_id} failed: {res}")
                return None
            codes = {i.get("code"): i.get("value") for i in res["result"] if isinstance(i, dict)}
        except Exception as e:
            logger.debug(f"Cloud status error for {dev_id}: {e}")
            return None

        def first(*names):
            for n in names:
                v = codes.get(n)
                if v is not None and not isinstance(v, bool):
                    return v
            return None

        def temp(v):
            if not isinstance(v, (int, float)):
                return None
            v = float(v)
            return round(v / 100.0 if v > 500 else v / 10.0 if v > 45 else v, 1)

        is_on = False
        for n in ("switch", "switch_1", "Power", "power"):
            if isinstance(codes.get(n), bool):
                is_on = codes[n]
                break

        cur = temp(first("temp_current", "va_temperature", "temp_indoor"))
        tgt = temp(first("temp_set", "set_temp", "target_temp"))
        hum = first("humidity_value", "va_humidity", "humidity_current")
        bat = first("battery_percentage", "battery")

        # Motion detector: pir / presence_state are "pir"|"presence" when triggered and "none" when clear
        motion_val = next((codes[n] for n in ("pir", "presence_state") if isinstance(codes.get(n), str)), None)
        if motion_val is not None:
            state["type"] = "sensor"
            state["motion"] = motion_val.lower() not in ("none", "clear", "off")
            state["is_motion_sensor"] = True
            state["battery_state"] = BATTERY_STATE_LABELS.get(str(codes.get("battery_state", "")).lower())
            cur = hum = None
        # Door / window contact sensor: doorcontact_state is true when open
        contact = next((codes[n] for n in ("doorcontact_state", "contact_state") if isinstance(codes.get(n), bool)), None)
        if contact is not None:
            state["type"] = "sensor"
            state["contact_open"] = contact
            state["battery_state"] = BATTERY_STATE_LABELS.get(str(codes.get("battery_state", "")).lower())
            cur = hum = None
        if state.get("type") in ("switch", "socket"):
            state["channels"] = extract_switch_channels(codes, cloud=True)

        state.update({
            "online": True,
            "is_on": is_on,
            "current_temperature": cur if cur is not None else state.get("current_temperature"),
            "target_temperature": tgt if tgt is not None else state.get("target_temperature"),
            "humidity": int(hum) if isinstance(hum, (int, float)) else state.get("humidity"),
            "battery": int(bat) if isinstance(bat, (int, float)) else state.get("battery"),
            "source": "cloud",
            "cloud_codes": codes,
            "error": None
        })
        return state

    async def get_all_states(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Returns current device states (cached in-memory for instant response, or forced refresh)."""
        if force_refresh and self.local_devices:
            loop = asyncio.get_event_loop()
            tasks = [
                loop.run_in_executor(None, self._sync_poll_device, dev_id)
                for dev_id in self.local_devices.keys()
            ]
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=2.5)
            except Exception:
                pass
        return list(self.device_states.values())

    async def set_device_power(self, dev_id: str, is_on: bool, channel: int = 1) -> bool:
        """Toggles power for a device (or one line of a multi-line switch)."""
        dev = self.local_devices.get(dev_id)
        if not dev:
            # Fallback to cloud if configured
            success = await self._set_cloud_power(dev_id, is_on, channel)
        else:
            def _set_power():
                try:
                    # Only pass `switch` for lines beyond the first: BulbDevice defaults to switch=0 (auto-detect)
                    kwargs = {"switch": channel} if channel > 1 else {}
                    if is_on:
                        dev.turn_on(**kwargs)
                    else:
                        dev.turn_off(**kwargs)
                    return True
                except Exception as e:
                    logger.error(f"Error setting power for {dev_id} line {channel}: {e}")
                    return False

            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, _set_power)
        if success and dev_id in self.device_states:
            st = self.device_states[dev_id]
            channels = st.get("channels") or []
            if channels:
                for ch in channels:
                    if ch["index"] == channel:
                        ch["is_on"] = is_on
                st["is_on"] = any(ch["is_on"] for ch in channels)
            else:
                st["is_on"] = is_on
            if dev:
                st["online"] = True
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
                device.set_socketTimeout(1.5)
                device.set_socketRetryLimit(1)
                res = device.status()
                if res and "dps" in res:
                    return {"success": True, "dps": res["dps"]}
                else:
                    return {"success": False, "error": res.get("Error", "No status received")}
            except Exception as e:
                return {"success": False, "error": str(e)}

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _test)

    def _fetch_home_room_map(self, uid: str, cloud_devices: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Dict[str, str]]:
        """Maps device id -> {"home": name, "room": name} from the Tuya Cloud. Problems are kept in self.location_errors."""
        result: Dict[str, Dict[str, str]] = {}
        self.location_errors = []
        if not self.cloud_api:
            self.location_errors.append("Tuya Cloud is not connected (check Access ID / Secret)")
            return result

        def _get(path):
            try:
                res = self.cloud_api.get(path)
                if res and res.get("success"):
                    return res.get("result")
                msg = f"{path}: {(res or {}).get('msg', 'no response')}"
            except Exception as e:
                msg = f"{path}: {e}"
            logger.info(f"Tuya Cloud {msg}")
            self.location_errors.append(msg)
            return None

        # Preferred: homes API (needs the User ID)
        homes = _get(f"/v1.0/users/{uid}/homes") if uid else None
        if not uid:
            self.location_errors.append("Tuya User ID is not set in Admin, so homes cannot be listed")
        home_names: Dict[Any, str] = {}
        for h in homes if isinstance(homes, list) else []:
            home_id, home_name = h.get("home_id"), h.get("name", "")
            if not home_id:
                continue
            home_names[str(home_id)] = home_name
            for dev in (_get(f"/v1.0/homes/{home_id}/devices") or []):
                if isinstance(dev, dict) and dev.get("id"):
                    result[dev["id"]] = {"home": home_name, "room": ""}
            rooms = _get(f"/v1.0/homes/{home_id}/rooms") or {}
            for r in (rooms.get("rooms", []) if isinstance(rooms, dict) else rooms):
                room_id, room_name = r.get("room_id"), r.get("name", "")
                if not room_id:
                    continue
                room_devs = _get(f"/v1.0/homes/{home_id}/rooms/{room_id}/devices") or []
                for d in (room_devs.get("devices", []) if isinstance(room_devs, dict) else room_devs):
                    dev_id = d.get("id") if isinstance(d, dict) else d
                    if dev_id:
                        result.setdefault(dev_id, {"home": home_name, "room": ""})["room"] = room_name

        # Fallback: every Tuya device record carries owner_id (= its home id)
        for d in cloud_devices or []:
            dev_id, owner = d.get("id"), d.get("owner_id")
            if not dev_id or not owner or dev_id in result:
                continue
            owner = str(owner)
            if owner not in home_names:
                info = _get(f"/v1.0/homes/{owner}")
                home_names[owner] = (info or {}).get("name") or f"Home {owner}"
            result[dev_id] = {"home": home_names[owner], "room": ""}

        logger.info(f"Tuya Cloud home/room map: {len(result)} devices, {len(set(v['home'] for v in result.values()))} homes")
        return result

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
                                "product_name": d.get("product_name", ""),
                                "ip": d.get("ip", "")
                            }

            home_room_map = self._fetch_home_room_map(uid, cloud_devices_list if isinstance(cloud_devices_list, list) else [])

            # Method 3: Direct per-device lookup via OpenAPI (/v1.0/devices/{id})
            updated_count = 0
            for dev in self.config.devices:
                loc = home_room_map.get(dev.id)
                if loc:
                    dev.home = loc["home"]
                    dev.room = loc["room"]
                info = cloud_key_map.get(dev.id, {})
                key = info.get("key")
                name = info.get("name")
                category = info.get("category", "")
                product_name = info.get("product_name", "")

                if (not key or not category) and self.cloud_api:
                    try:
                        d_res = self.cloud_api.get(f"/v1.0/devices/{dev.id}")
                        if d_res and d_res.get("success") and "result" in d_res:
                            r = d_res["result"]
                            key = r.get("local_key") or r.get("key")
                            name = r.get("name") or dev.name
                            category = category or r.get("category", "")
                            product_name = product_name or r.get("product_name", "")
                            logger.info(f"Fetched key directly for {dev.id} ({name}): key_found={bool(key)}")
                    except Exception as err:
                        logger.debug(f"Direct device {dev.id} lookup error: {err}")

                if category:
                    dev.category = category
                    dev.type = resolve_tuya_device_type(category, product_name, name or dev.name)
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
                "homes_matched": len(home_room_map),
                "location_errors": self.location_errors[:4],
                "api_errors": api_errors,
                "devices": [d.model_dump() for d in self.config.devices]
            }

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync)

    async def set_device_temperature(self, dev_id: str, temperature: float) -> bool:
        """Sets target desired temperature for thermostat/heating/climate device."""
        target_temp = round(float(temperature), 1)
        state = self.device_states.get(dev_id, {})
        dev = self.local_devices.get(dev_id)

        # 1. Determine DPS key and scale factor
        target_key = state.get("target_dps_key")
        scale = state.get("target_scale", 10)
        dps = state.get("dps", {})

        if not target_key:
            # Fallback scan across common Tuya setpoint DPS keys
            for k in ['16', '101', '103', '105', '106', '4', '2', '24']:
                if k in dps and isinstance(dps[k], (int, float)) and not isinstance(dps[k], bool):
                    target_key = k
                    if dps[k] > 500:
                        scale = 100
                    elif dps[k] > 45:
                        scale = 10
                    else:
                        scale = 1
                    break

        if not target_key:
            target_key = '16'  # Standard Tuya DP for temp_set
            scale = 10

        # Calculate integer value to send based on scale
        if scale == 100:
            val = int(round(target_temp * 100))
        elif scale == 10:
            val = int(round(target_temp * 10))
        else:
            val = int(round(target_temp))

        def _send_local():
            if not dev:
                return False
            try:
                # Primary method: set_value (tinytuya handles int/str key)
                key_to_send = int(target_key) if str(target_key).isdigit() else target_key
                res = dev.set_value(key_to_send, val)
                logger.info(f"Set target temperature for {dev_id} to {target_temp}°C (DPS {target_key}={val}): {res}")
                if isinstance(res, dict) and "Error" in res:
                    logger.warning(f"Device returned error for set_value DPS {target_key}={val}: {res}")
                    # Try fallback with multiple values dict
                    res_alt = dev.set_multiple_values({str(target_key): val})
                    logger.info(f"Fallback set_multiple_values for {dev_id}: {res_alt}")
                    if isinstance(res_alt, dict) and "Error" in res_alt:
                        return False
                return True
            except Exception as e:
                logger.error(f"Error setting local temperature for {dev_id}: {e}")
                return False

        loop = asyncio.get_event_loop()
        success = False
        if dev:
            success = await loop.run_in_executor(None, _send_local)

        # Fallback to cloud if local failed or not configured
        if not success and self.cloud_api:
            success = await self._set_cloud_temperature(dev_id, target_temp, scale)

        if success:
            if dev_id in self.device_states:
                self.device_states[dev_id]["target_temperature"] = target_temp
                self.device_states[dev_id]["online"] = True
                if "dps" in self.device_states[dev_id]:
                    self.device_states[dev_id]["dps"][str(target_key)] = val
            logger.info(f"Successfully updated target temperature for {dev_id} to {target_temp}°C")

        return success

    async def feed_pet(self, dev_id: str, portions: int = 1) -> bool:
        """Dispenses food for a smart pet feeder."""
        dev = self.local_devices.get(dev_id)

        def _feed():
            if not dev:
                return False
            try:
                state = self.device_states.get(dev_id, {})
                dps = state.get("dps", {})

                # Check which DPS controls manual feed
                feed_dps = None
                for key in ['3', '101', '4', '102', '1', '2']:
                    if key in dps:
                        feed_dps = int(key) if str(key).isdigit() else key
                        break

                if feed_dps is None:
                    feed_dps = 3  # standard Tuya pet feeder manual_feed DPS

                res = dev.set_value(feed_dps, portions)
                logger.info(f"Dispensed {portions} portion(s) for pet feeder {dev_id} (DPS {feed_dps}): {res}")
                if isinstance(res, dict) and "Error" in res:
                    res_alt = dev.set_multiple_values({str(feed_dps): portions})
                    logger.info(f"Fallback set_multiple_values for pet feeder {dev_id}: {res_alt}")
                    if isinstance(res_alt, dict) and "Error" in res_alt:
                        return False
                return True
            except Exception as e:
                logger.error(f"Error feeding pet on {dev_id}: {e}")
                return False

        loop = asyncio.get_event_loop()
        success = False
        if dev:
            success = await loop.run_in_executor(None, _feed)

        # Fallback to cloud if local failed
        if not success and self.cloud_api:
            success = await self._set_cloud_feed(dev_id, portions)

        if success and dev_id in self.device_states:
            now = datetime.datetime.now()
            self.device_states[dev_id]["last_fed"] = now.strftime("%H:%M")
            self._feed_log.setdefault(dev_id, []).append((now.timestamp(), portions))
            self._feeding_fetched_at.pop(dev_id, None)  # re-read the cloud log on the next poll
            self._update_feeding_state(dev_id, self._today_records_from_log(dev_id))
        return success

    # ----- Pet feeder: today's feeding records -----

    @staticmethod
    def _midnight_ts() -> float:
        return datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def _today_records_from_log(self, dev_id: str) -> List[Dict[str, Any]]:
        """Feeds triggered through HomeAuto today (used when the Tuya Cloud log is unavailable)."""
        midnight = self._midnight_ts()
        return [
            {"time": datetime.datetime.fromtimestamp(ts).strftime("%H:%M"), "portions": p, "ts": ts}
            for ts, p in self._feed_log.get(dev_id, []) if ts >= midnight
        ]

    def _update_feeding_state(self, dev_id: str, records: List[Dict[str, Any]], source: str = "homeauto"):
        st = self.device_states.get(dev_id)
        if st is None:
            return
        records = sorted(records, key=lambda r: r["ts"], reverse=True)
        st["feeding_records"] = [{"time": r["time"], "portions": r["portions"]} for r in records]
        st["feeding_total"] = sum(r["portions"] for r in records)
        st["feeding_source"] = source
        if records:
            st["last_fed"] = records[0]["time"]

    def _fetch_cloud_feeding_records(self, dev_id: str) -> Optional[List[Dict[str, Any]]]:
        """Reads today's feeding events from the Tuya Cloud device log. Returns None when the log is unavailable."""
        if not self.cloud_api:
            return None
        params = {"start_time": int(self._midnight_ts() * 1000), "end_time": int(time.time() * 1000),
                  "type": "7", "size": 100, "query_type": 1}
        logs = []
        try:
            for _ in range(5):  # at most 500 events
                res = self.cloud_api.get(f"/v1.0/devices/{dev_id}/logs", dict(params))
                if not (res and res.get("success") and isinstance(res.get("result"), dict)):
                    logger.debug(f"Cloud feeding log for {dev_id} failed: {res}")
                    return None
                result = res["result"]
                logs += [l for l in result.get("logs") or [] if isinstance(l, dict)]
                if not (result.get("has_next") and result.get("next_row_key")):
                    break
                params["start_row_key"] = result["next_row_key"]
        except Exception as e:
            logger.debug(f"Cloud feeding log error for {dev_id}: {e}")
            return None

        def portions_of(value):
            try:
                return max(1, int(float(value)))
            except (TypeError, ValueError):
                return 1

        # One feed can be logged under several codes, so use the first code that has events today
        for code in FEED_LOG_CODES:
            entries = [l for l in logs if l.get("code") == code and l.get("event_time")]
            if code == "feed_state":
                entries = [l for l in entries if str(l.get("value")).lower() == "feeding"]
            if entries:
                records = []
                for l in entries:
                    ts = float(l["event_time"]) / 1000.0
                    records.append({
                        "time": datetime.datetime.fromtimestamp(ts).strftime("%H:%M"),
                        "portions": 1 if code == "feed_state" else portions_of(l.get("value")),
                        "ts": ts,
                    })
                return records
        return []

    def _refresh_feeding_records(self, dev_id: str):
        """Runs in the poll worker: refreshes a pet feeder's records at most every FEEDING_REFRESH_SECONDS."""
        st = self.device_states.get(dev_id)
        if not st or st.get("type") != "pet_feeder":
            return
        now = time.time()
        if now - self._feeding_fetched_at.get(dev_id, 0) < FEEDING_REFRESH_SECONDS:
            return
        self._feeding_fetched_at[dev_id] = now
        records = self._fetch_cloud_feeding_records(dev_id)
        if records is not None:
            self._update_feeding_state(dev_id, records, "cloud")
        else:
            self._update_feeding_state(dev_id, self._today_records_from_log(dev_id), "homeauto")

    async def _set_cloud_feed(self, dev_id: str, portions: int = 1) -> bool:
        if not self.cloud_api:
            return False

        def _send():
            try:
                commands = [{"code": "manual_feed", "value": portions}]
                res = self.cloud_api.post(f"/v1.0/devices/{dev_id}/commands", {"commands": commands})
                if res and res.get("success"):
                    return True
                commands_alt = [{"code": "feed", "value": portions}]
                res_alt = self.cloud_api.post(f"/v1.0/devices/{dev_id}/commands", {"commands": commands_alt})
                return bool(res_alt and res_alt.get("success"))
            except Exception as e:
                logger.error(f"Error sending cloud feed command to {dev_id}: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _send)

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

    async def _set_cloud_power(self, dev_id: str, is_on: bool, channel: int = 1) -> bool:
        if not self.cloud_api:
            return False
        
        def _send():
            try:
                # DP 1-6 are switch_1..6; the USB block of a power strip is DP 7+ (switch_usb1..)
                code = f"switch_{channel}" if channel <= 6 else f"switch_usb{channel - 6}"
                commands = [{"code": code, "value": is_on}]
                res = self.cloud_api.post(f"/v1.0/devices/{dev_id}/commands", {"commands": commands})
                return bool(res and res.get("success"))
            except Exception as e:
                logger.error(f"Error sending cloud power command to {dev_id}: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _send)

    async def _set_cloud_temperature(self, dev_id: str, temperature: float, scale: int = 10) -> bool:
        if not self.cloud_api:
            return False

        def _send():
            try:
                val = int(round(temperature * scale)) if scale > 1 else int(round(temperature))
                commands = [{"code": "temp_set", "value": val}]
                res = self.cloud_api.post(f"/v1.0/devices/{dev_id}/commands", {"commands": commands})
                if res and res.get("success"):
                    return True
                commands_alt = [{"code": "target_temp", "value": val}]
                res_alt = self.cloud_api.post(f"/v1.0/devices/{dev_id}/commands", {"commands": commands_alt})
                return bool(res_alt and res_alt.get("success"))
            except Exception as e:
                logger.error(f"Error sending cloud temperature command to {dev_id}: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _send)
