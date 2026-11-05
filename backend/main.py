import os
import asyncio
import logging
from typing import List, Dict, Any, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("HomeAuto.Server")

# Global instances
config: AppConfig = load_config()
tuya_mgr = TuyaManager(config.tuya)
bt_mgr = BluetoothAudioManager(config.bluetooth_audio)
kodi_mgr = KodiManager(config.kodi)
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
        except Exception as e:
            logger.debug(f"Telemetry sync loop error: {e}")
        await asyncio.sleep(3.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing HomeAuto platform services...")
    bt_mgr.start_background_service()
    sync_task = asyncio.create_task(background_telemetry_and_sync())
    yield
    # Shutdown
    logger.info("Shutting down HomeAuto platform services...")
    sync_task.cancel()
    bt_mgr.stop_background_service()
    media_player.stop()

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
@app.get("/api/devices")
async def list_devices():
    return await tuya_mgr.get_all_states()

@app.post("/api/devices/{device_id}/power")
async def set_device_power(device_id: str, payload: Dict[str, bool] = Body(...)):
    is_on = payload.get("is_on", True)
    success = await tuya_mgr.set_device_power(device_id, is_on)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to communicate with Tuya device")
    return {"status": "ok", "device_id": device_id, "is_on": is_on}

@app.post("/api/devices/{device_id}/brightness")
async def set_device_brightness(device_id: str, payload: Dict[str, int] = Body(...)):
    brightness = payload.get("brightness", 100)
    success = await tuya_mgr.set_device_brightness(device_id, brightness)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to adjust brightness")
    return {"status": "ok", "device_id": device_id, "brightness": brightness}

@app.post("/api/devices/scan")
async def scan_tuya_devices():
    local_devs = await tuya_mgr.scan_local_network()
    cloud_devs = await tuya_mgr.fetch_cloud_devices()
    return {"local": local_devs, "cloud": cloud_devs}

# Bluetooth Surround Sound
@app.get("/api/bluetooth")
async def get_bluetooth_status():
    return await bt_mgr.check_connection_status()

@app.get("/api/bluetooth/scan")
async def scan_bluetooth_devices():
    return await bt_mgr.scan_devices()

@app.post("/api/bluetooth/connect")
async def connect_bluetooth(payload: Dict[str, str] = Body(...)):
    mac = payload.get("mac")
    if not mac:
        raise HTTPException(status_code=400, detail="MAC address required")
    success = await bt_mgr.connect_device(mac)
    return {"status": "ok" if success else "failed", "connected": success}

@app.post("/api/bluetooth/disconnect")
async def disconnect_bluetooth():
    success = await bt_mgr.disconnect_device()
    return {"status": "ok" if success else "failed"}

@app.post("/api/bluetooth/volume")
async def set_bluetooth_volume(payload: Dict[str, int] = Body(...)):
    vol = payload.get("volume", 70)
    new_vol = await bt_mgr.set_volume(vol)
    return {"volume": new_vol}

# Kodi Integration
@app.get("/api/kodi")
async def get_kodi_status():
    return await kodi_mgr.get_status()

@app.post("/api/kodi/play_pause")
async def kodi_play_pause():
    success = await kodi_mgr.play_pause()
    return {"status": "ok" if success else "failed"}

@app.post("/api/kodi/stop")
async def kodi_stop():
    success = await kodi_mgr.stop()
    return {"status": "ok" if success else "failed"}

@app.post("/api/kodi/input")
async def kodi_input(payload: Dict[str, str] = Body(...)):
    action = payload.get("action", "")
    success = await kodi_mgr.send_input(action)
    return {"status": "ok" if success else "failed"}

@app.post("/api/kodi/launch")
async def kodi_launch():
    success = await kodi_mgr.launch_kodi()
    return {"status": "ok" if success else "failed"}

@app.post("/api/kodi/quit")
async def kodi_quit():
    success = await kodi_mgr.quit_kodi()
    return {"status": "ok" if success else "failed"}

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

# Frontend Static Files Mount
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=config.server.host, port=config.server.port, reload=config.server.debug)
