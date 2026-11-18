"""
Pi-side Bluetooth agent for kiosk-only installs.

When the Pi only runs the Chromium kiosk and the HomeAuto server lives elsewhere (LXC, VM, ...),
the server cannot scan/pair the Pi's Bluetooth adapter or route the Pi's audio. This small service runs
on the Pi, listens on 127.0.0.1 only and exposes the same /api/bluetooth/* endpoints as the server.
The web UI detects it (see frontend/js/bt_audio.js) and talks to it instead of the server.

Run: python -m backend.pi_agent   (needs only fastapi, uvicorn, pydantic, pyyaml)
"""
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Request, Response

from backend.bt_audio_manager import BluetoothAudioManager
from backend.config import BluetoothAudioConfig

logger = logging.getLogger("HomeAuto.PiAgent")

PORT = int(os.environ.get("HOMEAUTO_AGENT_PORT", "8765"))
CONFIG_PATH = Path(os.environ.get("HOMEAUTO_AGENT_CONFIG", Path(__file__).resolve().parent.parent / "pi_agent.json"))


def _load_config() -> BluetoothAudioConfig:
    try:
        return BluetoothAudioConfig(**json.loads(CONFIG_PATH.read_text()))
    except FileNotFoundError:
        return BluetoothAudioConfig()
    except Exception as e:
        logger.warning(f"Ignoring unreadable {CONFIG_PATH}: {e}")
        return BluetoothAudioConfig()


def _save_config():
    CONFIG_PATH.write_text(json.dumps(bt_mgr.config.model_dump(), indent=2))


def _ensure_supervisor():
    """Starts the auto-reconnect loop once a target speaker is known."""
    task = bt_mgr._reconnect_task
    if task is None or task.done():
        bt_mgr.start_background_service()


bt_mgr = BluetoothAudioManager(_load_config())


@asynccontextmanager
async def lifespan(_: FastAPI):
    bt_mgr.start_background_service()
    yield
    bt_mgr.stop_background_service()


app = FastAPI(title="HomeAuto Pi Agent", lifespan=lifespan)


@app.middleware("http")
async def cors(request: Request, call_next):
    # The page is served by the remote HomeAuto server, so calls to this agent are cross-origin.
    # Access-Control-Allow-Private-Network is required by Chromium for public/private page -> loopback requests.
    response = Response(status_code=204) if request.method == "OPTIONS" else await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.get("/api/health")
async def health():
    return {"agent": True}


@app.get("/api/bluetooth")
async def get_bluetooth_status():
    return await bt_mgr.check_connection_status()


@app.get("/api/bluetooth/scan")
async def scan_bluetooth_devices(seconds: int = 10):
    return await bt_mgr.scan_devices(seconds)


@app.post("/api/bluetooth/connect")
async def connect_bluetooth(payload: Dict[str, str] = Body(...)):
    mac = payload.get("mac")
    if not mac:
        raise HTTPException(status_code=400, detail="MAC address required")
    success = await bt_mgr.connect_device(mac)
    if success:
        bt_mgr.config.enabled = True
        _save_config()
        _ensure_supervisor()
    return {"status": "ok" if success else "failed", "connected": success, "name": bt_mgr.current_device_name}


@app.post("/api/bluetooth/disconnect")
async def disconnect_bluetooth():
    success = await bt_mgr.disconnect_device()
    return {"status": "ok" if success else "failed"}


@app.post("/api/bluetooth/volume")
async def set_bluetooth_volume(payload: Dict[str, int] = Body(...)):
    new_vol = await bt_mgr.set_volume(payload.get("volume", 70))
    bt_mgr.config.default_volume = new_vol
    _save_config()
    return {"volume": new_vol}


@app.post("/api/bluetooth/test-sound")
async def test_bluetooth_sound():
    if bt_mgr.config.target_mac:
        await bt_mgr.switch_to_bluetooth_sink(bt_mgr.config.target_mac)
    res = await bt_mgr.play_test_tone()
    return {"status": "ok" if res.get("success") else "failed", **res}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
