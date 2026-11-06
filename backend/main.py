import os
import asyncio
import logging
from typing import List, Dict, Any, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import requests

from backend.config import load_config, save_config, AppConfig
from backend.tuya_manager import TuyaManager
from backend.bt_audio_manager import BluetoothAudioManager
from backend.kodi_manager import KodiManager
from backend.media_player import MediaPlayer
from backend.screensaver_manager import ScreensaverManager
from backend.system_manager import SystemManager
from backend import pi_control

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("HomeAuto.Server")

# Global instances
config: AppConfig = load_config()
tuya_mgr = TuyaManager(config.tuya)
bt_mgr = BluetoothAudioManager(config.bluetooth_audio)
kodi_mgr = KodiManager(config.kodi)
kodi_mgr.own_port = config.server.port
media_player = MediaPlayer(config.screensaver.youtube_audio)
screensaver_mgr = ScreensaverManager(config.screensaver)

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        dead = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for d in dead:
            self.active_connections.discard(d)

ws_manager = ConnectionManager()

# Background state broadcaster
async def background_telemetry_and_sync():
    while True:
        try:
            device_states = await tuya_mgr.get_all_states()
            bt_status = await bt_mgr.check_connection_status()
            kodi_status = await kodi_mgr.get_status()
            telemetry = SystemManager.get_telemetry()
            media_status = media_player.get_status()

            payload = {
                "type": "state_update",
                "data": {
                    "devices": device_states,
                    "bluetooth": bt_status,
                    "kodi": kodi_status,
                    "system": telemetry,
                    "media": media_status
                }
            }
            await ws_manager.broadcast(payload)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Telemetry sync loop error: {e}")

        try:
            await asyncio.sleep(3.0)
        except asyncio.CancelledError:
            break

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing HomeAuto platform services...")
    tuya_mgr.start_background_service()
    bt_mgr.start_background_service()
    sync_task = asyncio.create_task(background_telemetry_and_sync())
    yield
    # Shutdown
    logger.info("Shutting down HomeAuto platform services...")
    sync_task.cancel()
    tuya_mgr.stop_background_service()
    bt_mgr.stop_background_service()
    media_player.stop()
    try:
        await asyncio.wait_for(asyncio.shield(sync_task), timeout=0.5)
    except Exception:
        pass

app = FastAPI(title="HomeAuto Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- WebSocket Endpoint -----------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        # Send initial full state
        device_states = await tuya_mgr.get_all_states()
        bt_status = await bt_mgr.check_connection_status()
        kodi_status = await kodi_mgr.get_status()
        telemetry = SystemManager.get_telemetry()
        media_status = media_player.get_status()

        await websocket.send_json({
            "type": "initial_state",
            "data": {
                "devices": device_states,
                "bluetooth": bt_status,
                "kodi": kodi_status,
                "system": telemetry,
                "media": media_status,
                "screensaver": screensaver_mgr.get_settings()
            }
        })

        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            if action == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.debug(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)

# ----------------- REST Endpoints -----------------

@app.get("/api/status")
async def get_full_status():
    return {
        "devices": await tuya_mgr.get_all_states(),
        "bluetooth": await bt_mgr.check_connection_status(),
        "kodi": await kodi_mgr.get_status(),
        "system": SystemManager.get_telemetry(),
        "media": media_player.get_status(),
        "screensaver": screensaver_mgr.get_settings()
    }

# Tuya / SmartLife Devices
@app.get("/api/tuya/realtime")
async def tuya_realtime_status():
    return tuya_mgr.realtime_status()

@app.get("/api/devices")
async def list_devices():
    return await tuya_mgr.get_all_states()

@app.post("/api/devices/{device_id}/power")
async def set_device_power(device_id: str, payload: Dict[str, Any] = Body(...)):
    is_on = bool(payload.get("is_on", True))
    channel = int(payload.get("channel", 1))  # line number for multi-line switches
    success = await tuya_mgr.set_device_power(device_id, is_on, channel)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to communicate with Tuya device")
    await ws_manager.broadcast({
        "type": "state_update",
        "data": { "devices": await tuya_mgr.get_all_states() }
    })
    return {"status": "ok", "device_id": device_id, "is_on": is_on}

@app.post("/api/devices/{device_id}/brightness")
async def set_device_brightness(device_id: str, payload: Dict[str, int] = Body(...)):
    brightness = payload.get("brightness", 100)
    success = await tuya_mgr.set_device_brightness(device_id, brightness)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to adjust brightness")
    await ws_manager.broadcast({
        "type": "state_update",
        "data": { "devices": await tuya_mgr.get_all_states() }
    })
    return {"status": "ok", "device_id": device_id, "brightness": brightness}

@app.post("/api/devices/{device_id}/temperature")
async def set_device_temperature(device_id: str, payload: Dict[str, float] = Body(...)):
    temperature = payload.get("temperature", 21.0)
    success = await tuya_mgr.set_device_temperature(device_id, float(temperature))
    if not success:
        raise HTTPException(status_code=500, detail="Failed to set target temperature")
    await ws_manager.broadcast({
        "type": "state_update",
        "data": { "devices": await tuya_mgr.get_all_states() }
    })
    return {"status": "ok", "device_id": device_id, "target_temperature": temperature}

@app.post("/api/devices/{device_id}/ac")
async def set_device_ac_option(device_id: str, payload: Dict[str, str] = Body(...)):
    option = payload.get("option", "")
    value = payload.get("value", "")
    success = await tuya_mgr.set_ac_option(device_id, option, value)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to set air conditioner option")
    await ws_manager.broadcast({
        "type": "state_update",
        "data": { "devices": await tuya_mgr.get_all_states() }
    })
    return {"status": "ok", "device_id": device_id, option: value}

@app.post("/api/devices/{device_id}/feed")
async def feed_pet_endpoint(device_id: str, payload: Dict[str, int] = Body(default={"portions": 1})):
    portions = payload.get("portions", 1)
    success = await tuya_mgr.feed_pet(device_id, int(portions))
    if not success:
        raise HTTPException(status_code=500, detail="Failed to trigger pet feeding")
    await ws_manager.broadcast({
        "type": "state_update",
        "data": { "devices": await tuya_mgr.get_all_states() }
    })
    return {"status": "ok", "device_id": device_id, "portions": portions}

@app.post("/api/devices/scan")
async def scan_tuya_devices():
    discovered = await tuya_mgr.scan_and_discover_devices()
    return {"discovered": discovered, "count": len(discovered)}

@app.post("/api/devices/import-batch")
async def import_devices_batch(payload: Dict[str, Any] = Body(...)):
    global config
    devices_to_import = payload.get("devices", [])
    if not devices_to_import:
        raise HTTPException(status_code=400, detail="No devices provided for import")
    
    from backend.config import TuyaDeviceConfig
    imported_count = 0
    existing_ids = {d.id for d in config.tuya.devices}

    for dev_raw in devices_to_import:
        dev_id = dev_raw.get("id")
        if not dev_id:
            continue
        
        # If already configured, update IP / key
        if dev_id in existing_ids:
            for idx, existing in enumerate(config.tuya.devices):
                if existing.id == dev_id:
                    if dev_raw.get("ip"):
                        existing.ip = dev_raw.get("ip")
                    if dev_raw.get("local_key"):
                        existing.local_key = dev_raw.get("local_key")
                    if dev_raw.get("home"):  # cloud-derived location; only then trust the room too
                        existing.home = dev_raw.get("home")
                        if dev_raw.get("room"):
                            existing.room = dev_raw.get("room")
                    if dev_raw.get("category"):
                        existing.category = dev_raw.get("category")
                        existing.type = dev_raw.get("type") or existing.type
                    config.tuya.devices[idx] = existing
        else:
            new_dev = TuyaDeviceConfig(
                id=dev_id,
                name=dev_raw.get("name") or f"Tuya Device {dev_id[-4:]}",
                ip=dev_raw.get("ip") or "",
                local_key=dev_raw.get("local_key") or "",
                version=float(dev_raw.get("version") or 3.3),
                type=dev_raw.get("type") or "switch",
                category=dev_raw.get("category") or "cz",
                room=dev_raw.get("room") or "",
                home=dev_raw.get("home") or ""
            )
            config.tuya.devices.append(new_dev)
            existing_ids.add(dev_id)
            imported_count += 1

    save_config(config)
    tuya_mgr.reload_config(config.tuya)
    new_states = await tuya_mgr.get_all_states()
    await ws_manager.broadcast({
        "type": "state_update",
        "data": {
            "devices": new_states
        }
    })
    return {
        "status": "ok",
        "imported_count": imported_count,
        "total_devices": len(config.tuya.devices),
        "devices": new_states
    }

@app.post("/api/devices/test")
async def test_tuya_device(payload: Dict[str, Any] = Body(...)):
    dev_id = payload.get("id", "")
    ip = payload.get("ip", "")
    local_key = payload.get("local_key", "")
    version = float(payload.get("version", 3.3))
    return await tuya_mgr.test_connection(dev_id, ip, local_key, version)

@app.post("/api/tuya/cloud/sync-keys")
async def sync_tuya_cloud_keys():
    global config
    result = await tuya_mgr.sync_all_cloud_keys()
    if result.get("success"):
        # Save updated keys to config
        save_config(config)
        tuya_mgr.reload_config(config.tuya)
        new_states = await tuya_mgr.get_all_states()
        await ws_manager.broadcast({
            "type": "state_update",
            "data": {
                "devices": new_states
            }
        })
    return result

# Kodi JSON-RPC Proxy / Catch-all to prevent 405 Method Not Allowed
@app.post("/jsonrpc")
@app.get("/jsonrpc")
async def jsonrpc_endpoint(payload: Dict[str, Any] = Body(default={})):
    return {"jsonrpc": "2.0", "result": "pong", "id": payload.get("id", 1)}

# Bluetooth Surround Sound & Audio Routing
@app.get("/api/bluetooth")
async def get_bluetooth_status():
    return await bt_mgr.check_connection_status()

@app.get("/api/bluetooth/sinks")
async def get_audio_sinks():
    return await bt_mgr.get_audio_sinks()

@app.post("/api/bluetooth/switch-sink")
async def switch_audio_sink(payload: Dict[str, str] = Body(...)):
    sink_or_mac = payload.get("sink") or payload.get("mac", "")
    success = await bt_mgr.switch_to_bluetooth_sink(sink_or_mac)
    return {"status": "ok" if success else "failed"}

@app.get("/api/bluetooth/scan")
async def scan_bluetooth_devices():
    return await bt_mgr.scan_devices()

@app.post("/api/bluetooth/connect")
async def connect_bluetooth(payload: Dict[str, str] = Body(...)):
    global config
    mac = payload.get("mac")
    if not mac:
        raise HTTPException(status_code=400, detail="MAC address required")
    success = await bt_mgr.connect_device(mac)
    if success:
        config.bluetooth_audio.target_mac = mac
        config.bluetooth_audio.device_name = bt_mgr.current_device_name
        config.bluetooth_audio.enabled = True
        save_config(config)
        await ws_manager.broadcast({
            "type": "state_update",
            "data": {
                "bluetooth": await bt_mgr.check_connection_status()
            }
        })
    return {"status": "ok" if success else "failed", "connected": success, "name": bt_mgr.current_device_name}

@app.post("/api/bluetooth/disconnect")
async def disconnect_bluetooth():
    success = await bt_mgr.disconnect_device()
    await ws_manager.broadcast({
        "type": "state_update",
        "data": {
            "bluetooth": await bt_mgr.check_connection_status()
        }
    })
    return {"status": "ok" if success else "failed"}

@app.post("/api/bluetooth/volume")
async def set_bluetooth_volume(payload: Dict[str, int] = Body(...)):
    global config
    vol = payload.get("volume", 70)
    new_vol = await bt_mgr.set_volume(vol)
    config.bluetooth_audio.default_volume = new_vol
    save_config(config)
    media_player.set_volume(new_vol)
    return {"volume": new_vol}

@app.post("/api/bluetooth/test-sound")
async def test_bluetooth_sound():
    if bt_mgr.config.target_mac:
        await bt_mgr.switch_to_bluetooth_sink(bt_mgr.config.target_mac)
    res = await bt_mgr.play_test_tone()
    return {"status": "ok" if res.get("success") else "failed", **res}

# Kodi Integration
@app.get("/api/kodi")
async def get_kodi_status():
    return await kodi_mgr.get_status()

def _kodi_result(success: bool):
    if success:
        return {"status": "ok"}
    return {"status": "failed", "error": kodi_mgr.last_error or "Kodi did not respond (is anything playing / is Kodi running?)"}

@app.post("/api/kodi/play_pause")
async def kodi_play_pause():
    return _kodi_result(await kodi_mgr.play_pause())

@app.post("/api/kodi/stop")
async def kodi_stop():
    return _kodi_result(await kodi_mgr.stop())

@app.post("/api/kodi/input")
async def kodi_input(payload: Dict[str, str] = Body(...)):
    action = payload.get("action", "")
    return _kodi_result(await kodi_mgr.send_input(action))

@app.post("/api/kodi/launch")
async def kodi_launch():
    return _kodi_result(await kodi_mgr.launch_kodi())

@app.post("/api/kodi/quit")
async def kodi_quit():
    success = await kodi_mgr.quit_kodi()
    return {"status": "ok" if success else "failed"}

@app.post("/api/kodi/test")
async def test_kodi_connection(payload: Dict[str, Any] = Body(...)):
    host = payload.get("host", "127.0.0.1")
    port = int(payload.get("port", 8080))
    user = payload.get("user", "")
    password = payload.get("password", "")
    return await kodi_mgr.test_connection(host, port, user, password)

# Background & YouTube Media Player
@app.get("/api/media")
async def get_media_status():
    return media_player.get_status()

@app.post("/api/media/play")
async def play_media(payload: Dict[str, Any] = Body(...)):
    url = payload.get("url")
    title = payload.get("title")
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    await media_player.play(url, title)
    return media_player.get_status()

@app.post("/api/media/pause")
async def pause_media():
    media_player.pause()
    return media_player.get_status()

@app.post("/api/media/stop")
async def stop_media():
    media_player.stop()
    return media_player.get_status()

@app.post("/api/media/volume")
async def set_media_volume(payload: Dict[str, int] = Body(...)):
    vol = payload.get("volume", 50)
    media_player.set_volume(vol)
    return {"volume": media_player.volume}

# Screensaver & Ambient
@app.get("/api/screensaver")
async def get_screensaver():
    return screensaver_mgr.get_settings()

# Weather (Open-Meteo free API with in-memory caching)
_cached_weather: Dict[str, Any] = {}
_cached_weather_time: float = 0

@app.get("/api/weather")
async def get_weather():
    global _cached_weather, _cached_weather_time
    import time
    now = time.time()
    if _cached_weather and (now - _cached_weather_time < 900): # 15 min cache
        return _cached_weather

    try:
        lat = config.weather.latitude
        lon = config.weather.longitude
        temp_unit = "fahrenheit" if config.weather.units == "fahrenheit" else "celsius"
        
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m&temperature_unit={temp_unit}"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            data = res.json().get("current", {})
            _cached_weather = {
                "temperature": data.get("temperature_2m", 21),
                "apparent_temperature": data.get("apparent_temperature", 21),
                "humidity": data.get("relative_humidity_2m", 50),
                "weather_code": data.get("weather_code", 0),
                "is_day": data.get("is_day", 1),
                "wind_speed": data.get("wind_speed_10m", 5),
                "units": "°F" if temp_unit == "fahrenheit" else "°C"
            }
            _cached_weather_time = now
            return _cached_weather
    except Exception as e:
        logger.debug(f"Weather API error: {e}")

    return _cached_weather or {
        "temperature": 21,
        "apparent_temperature": 21,
        "humidity": 45,
        "weather_code": 0,
        "is_day": 1,
        "wind_speed": 4,
        "units": "°C"
    }

# System Hardware Telemetry
@app.get("/api/system")
async def get_system_telemetry():
    return SystemManager.get_telemetry()

@app.post("/api/system/display")
async def toggle_display(payload: Dict[str, bool] = Body(...)):
    power_on = payload.get("power_on", True)
    success = SystemManager.set_display_power(power_on)
    return {"status": "ok" if success else "failed", "power_on": power_on}

# ----------------- Raspberry Pi controls (Wi-Fi, Bluetooth, desktop, power) -----------------
# These run system commands and the server has no login, so only requests from the Pi itself are accepted
# (the kiosk browser talks to 127.0.0.1). Other devices on the network get 403.

def _require_local(request: Request):
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"):
        raise HTTPException(status_code=403, detail="Raspberry Pi controls only work from the Pi's own screen (http://127.0.0.1)")

async def _pi(request: Request, func, *args):
    _require_local(request)
    return await asyncio.get_event_loop().run_in_executor(None, func, *args)

@app.get("/api/pi/status")
async def pi_status(request: Request):
    _require_local(request)
    loop = asyncio.get_event_loop()
    wifi, bt = await asyncio.gather(loop.run_in_executor(None, pi_control.wifi_status),
                                    loop.run_in_executor(None, pi_control.bluetooth_status))
    return {"local": True, "wifi": wifi, "bluetooth": bt}

@app.get("/api/pi/wifi/scan")
async def pi_wifi_scan(request: Request):
    return await _pi(request, pi_control.wifi_scan)

@app.post("/api/pi/wifi/power")
async def pi_wifi_power(request: Request, payload: Dict[str, Any] = Body(...)):
    return await _pi(request, pi_control.wifi_set_power, bool(payload.get("on")))

@app.post("/api/pi/wifi/connect")
async def pi_wifi_connect(request: Request, payload: Dict[str, Any] = Body(...)):
    return await _pi(request, pi_control.wifi_connect, str(payload.get("ssid", "")), str(payload.get("password", "")))

@app.post("/api/pi/bluetooth/power")
async def pi_bluetooth_power(request: Request, payload: Dict[str, Any] = Body(...)):
    return await _pi(request, pi_control.bluetooth_set_power, bool(payload.get("on")))

@app.post("/api/pi/desktop")
async def pi_open_desktop(request: Request, payload: Dict[str, Any] = Body(default={})):
    return await _pi(request, pi_control.open_desktop, payload.get("minutes", 10))

@app.post("/api/pi/dashboard")
async def pi_return_dashboard(request: Request):
    return await _pi(request, pi_control.return_to_dashboard)

@app.post("/api/pi/restart-kiosk")
async def pi_restart_kiosk(request: Request):
    return await _pi(request, pi_control.restart_kiosk)

@app.post("/api/pi/restart-app")
async def pi_restart_app(request: Request):
    return await _pi(request, pi_control.restart_app)

@app.post("/api/pi/power")
async def pi_power(request: Request, payload: Dict[str, Any] = Body(...)):
    return await _pi(request, pi_control.power, str(payload.get("action", "")))

# Location Auto-Detection
@app.post("/api/weather/detect-location")
async def detect_location():
    try:
        res = requests.get("http://ip-api.com/json/", timeout=4)
        if res.status_code == 200:
            data = res.json()
            if data.get("status") == "success":
                return {
                    "success": True,
                    "latitude": round(data.get("lat", 0), 4),
                    "longitude": round(data.get("lon", 0), 4),
                    "city": data.get("city", ""),
                    "country": data.get("country", "")
                }
    except Exception as e:
        logger.error(f"Error detecting location: {e}")
    return {"success": False, "error": "Could not auto-detect location"}

# ----------------- Full Admin Configuration Endpoints -----------------

@app.get("/api/config")
async def get_config():
    global config
    return config.model_dump()

@app.post("/api/config")
async def update_full_config(new_conf_data: Dict[str, Any] = Body(...)):
    global config, _cached_weather
    try:
        new_app_config = AppConfig(**new_conf_data)
        save_config(new_app_config)
        config = new_app_config
        
        # Hot-reload managers
        tuya_mgr.reload_config(config.tuya)
        bt_mgr.reload_config(config.bluetooth_audio)
        kodi_mgr.reload_config(config.kodi)
        kodi_mgr.own_port = config.server.port
        media_player.reload_config(config.screensaver.youtube_audio)
        screensaver_mgr.reload_config(config.screensaver)
        _cached_weather = {} # clear weather cache

        # Broadcast update to clients
        await ws_manager.broadcast({
            "type": "config_updated",
            "data": config.model_dump()
        })

        return {"status": "ok", "message": "Configuration saved & applied successfully"}
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid configuration data: {str(e)}")

@app.post("/api/config/devices")
async def add_config_device(device_data: Dict[str, Any] = Body(...)):
    global config
    try:
        from backend.config import TuyaDeviceConfig
        dev = TuyaDeviceConfig(**device_data)
        # Check if already exists
        existing = [d for d in config.tuya.devices if d.id == dev.id]
        if existing:
            raise HTTPException(status_code=400, detail=f"Device with ID {dev.id} already exists")
        
        config.tuya.devices.append(dev)
        save_config(config)
        tuya_mgr.reload_config(config.tuya)
        new_states = await tuya_mgr.get_all_states()
        await ws_manager.broadcast({
            "type": "state_update",
            "data": {
                "devices": new_states
            }
        })
        return {"status": "ok", "devices": [d.model_dump() for d in config.tuya.devices]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/config/devices/{device_id}")
async def update_config_device(device_id: str, device_data: Dict[str, Any] = Body(...)):
    global config
    try:
        from backend.config import TuyaDeviceConfig
        found = False
        for idx, d in enumerate(config.tuya.devices):
            if d.id == device_id:
                device_data["id"] = device_id
                config.tuya.devices[idx] = TuyaDeviceConfig(**device_data)
                found = True
                break
        if not found:
            raise HTTPException(status_code=404, detail="Device not found")
        
        save_config(config)
        tuya_mgr.reload_config(config.tuya)
        new_states = await tuya_mgr.get_all_states()
        await ws_manager.broadcast({
            "type": "state_update",
            "data": {
                "devices": new_states
            }
        })
        return {"status": "ok", "devices": [d.model_dump() for d in config.tuya.devices]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/config/devices/{device_id}")
async def delete_config_device(device_id: str):
    global config
    config.tuya.devices = [d for d in config.tuya.devices if d.id != device_id]
    save_config(config)
    tuya_mgr.reload_config(config.tuya)
    new_states = await tuya_mgr.get_all_states()
    await ws_manager.broadcast({
        "type": "state_update",
        "data": {
            "devices": new_states
        }
    })
    return {"status": "ok", "devices": [d.model_dump() for d in config.tuya.devices]}

# Frontend Static Files Mount
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=config.server.host, port=config.server.port, reload=config.server.debug)
