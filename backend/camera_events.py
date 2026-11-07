"""
Camera / doorbell event history: every doorbell ring (and person / motion alert) is logged with a snapshot,
so you can see who came by while you were away. Pictures are small JPEGs in data/camera_events/, and only the
newest KEEP events are kept. The Tuya cloud API cannot play back the SD card, so this is our own record.
"""
import asyncio
import json
import logging
import os
import threading
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from backend.config import PROJECT_ROOT

logger = logging.getLogger("HomeAuto.CameraEvents")

EVENTS_DIR = os.path.join(PROJECT_ROOT, "data", "camera_events")
KEEP = 60
COOLDOWN = {"ring": 15, "alert": 60}  # seconds between two logged events of one kind per camera (a ring sends several messages)


class CameraEventLog:
    def __init__(self,
                 take_snapshot: Callable[[str], Awaitable[Optional[bytes]]],
                 describe: Callable[[str], Tuple[str, bool]],
                 broadcast: Callable[[Dict[str, Any]], Awaitable[None]],
                 directory: str = EVENTS_DIR):
        """
        take_snapshot(dev_id) -> JPEG bytes or None; describe(dev_id) -> (camera name, is_battery_powered);
        broadcast(event) pushes a new event to the browsers.
        """
        self._take_snapshot = take_snapshot
        self._describe = describe
        self._broadcast = broadcast
        self._dir = directory
        self._index = os.path.join(directory, "events.json")
        self._lock = threading.Lock()
        self._last: Dict[Tuple[str, str], float] = {}
        self._events: List[Dict[str, Any]] = self._load()

    # ----- storage -----

    def _load(self) -> List[Dict[str, Any]]:
        try:
            with open(self._index, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [e for e in data if isinstance(e, dict) and e.get("id")]
        except (OSError, ValueError):
            return []

    def _save(self):
        os.makedirs(self._dir, exist_ok=True)
        tmp = self._index + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._events, f)
        os.replace(tmp, self._index)

    def _image_file(self, event_id: str) -> str:
        return os.path.join(self._dir, f"{event_id}.jpg")

    def _remove_image(self, event: Dict[str, Any]):
        if event.get("image"):
            try:
                os.remove(self._image_file(event["id"]))
            except OSError:
                pass

    def _store(self, dev_id: str, name: str, kind: str, label: str, jpeg: Optional[bytes]) -> Dict[str, Any]:
        with self._lock:
            ts = time.time()
            event = {"id": f"{int(ts * 1000)}-{dev_id[:6]}", "dev_id": dev_id, "dev_name": name,
                     "kind": kind, "label": label, "ts": ts, "image": bool(jpeg)}
            os.makedirs(self._dir, exist_ok=True)
            if jpeg:
                with open(self._image_file(event["id"]), "wb") as f:
                    f.write(jpeg)
            self._events.insert(0, event)
            for old in self._events[KEEP:]:
                self._remove_image(old)
            del self._events[KEEP:]
            self._save()
            return event

    # ----- public API -----

    @staticmethod
    def _public(event: Dict[str, Any]) -> Dict[str, Any]:
        return {**event, "image_url": f"/api/camera-events/{event['id']}/image" if event.get("image") else None}

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._public(e) for e in self._events]

    def image_path(self, event_id: str) -> Optional[str]:
        """Path of the stored picture. Looked up through the index, so a crafted id can never reach other files."""
        with self._lock:
            event = next((e for e in self._events if e["id"] == event_id and e.get("image")), None)
        if not event:
            return None
        path = self._image_file(event["id"])
        return path if os.path.exists(path) else None

    def clear(self):
        with self._lock:
            for event in self._events:
                self._remove_image(event)
            self._events = []
            self._save()

    async def capture(self, dev_id: str, kind: str, label: str):
        """Logs one event. Rings always get a picture; alerts only on mains-powered cameras (waking a battery camera drains it)."""
        try:
            now = time.time()
            if now - self._last.get((dev_id, kind), 0) < COOLDOWN.get(kind, 30):
                return
            self._last[(dev_id, kind)] = now
            name, battery = self._describe(dev_id)
            jpeg = None
            if kind == "ring" or not battery:
                try:
                    jpeg = await self._take_snapshot(dev_id)
                except Exception as e:
                    logger.warning(f"No picture for {kind} event of {name}: {getattr(e, 'detail', e)}")
            event = await asyncio.get_event_loop().run_in_executor(None, self._store, dev_id, name, kind, label, jpeg)
            logger.info(f"Camera event: {name}: {label}" + ("" if jpeg else " (no picture)"))
            await self._broadcast(self._public(event))
        except Exception as e:
            logger.error(f"Could not log camera event: {e}")
