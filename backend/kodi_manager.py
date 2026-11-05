import logging
import asyncio
import subprocess
import requests
from typing import Dict, Any, Optional
from backend.config import KodiConfig

logger = logging.getLogger("HomeAuto.Kodi")

class KodiManager:
    def __init__(self, config: KodiConfig):
        self.config = config
        self.rpc_url = f"http://{self.config.host}:{self.config.port}/jsonrpc"
        self.auth = (self.config.user, self.config.password) if self.config.user else None

    async def send_rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Sends a JSON-RPC request to Kodi."""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": 1
        }
        if params is not None:
            payload["params"] = params

        def _request():
            try:
                res = requests.post(self.rpc_url, json=payload, auth=self.auth, timeout=2.5)
                if res.status_code == 200:
                    return res.json().get("result")
            except Exception as e:
                logger.debug(f"Kodi RPC connection error to {self.rpc_url}: {e}")
            return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _request)

    async def get_status(self) -> Dict[str, Any]:
        """Gets current player status and currently playing item."""
        players = await self.send_rpc("Player.GetActivePlayers")
        if players is None:
            return {
                "online": False,
                "playing": False,
                "item": None
            }

        if not players:
            return {
                "online": True,
                "playing": False,
                "item": None
            }

        player_id = players[0].get("playerid", 1)
        item_info = await self.send_rpc("Player.GetItem", {
            "playerid": player_id,
            "properties": ["title", "artist", "album", "showtitle", "season", "episode", "thumbnail", "duration", "file"]
        })
        props = await self.send_rpc("Player.GetProperties", {
            "playerid": player_id,
            "properties": ["speed", "percentage", "time", "totaltime"]
        })

        return {
            "online": True,
            "playing": props.get("speed", 0) > 0 if props else True,
            "player_id": player_id,
            "item": item_info.get("item") if item_info else None,
            "properties": props
        }

    async def play_pause(self) -> bool:
        players = await self.send_rpc("Player.GetActivePlayers")
        if players:
            res = await self.send_rpc("Player.PlayPause", {"playerid": players[0].get("playerid", 1)})
            return res is not None
        return False

    async def stop(self) -> bool:
        players = await self.send_rpc("Player.GetActivePlayers")
        if players:
            res = await self.send_rpc("Player.Stop", {"playerid": players[0].get("playerid", 1)})
            return res is not None
        return False

    async def send_input(self, action: str) -> bool:
        """Sends GUI input actions (Up, Down, Left, Right, Select, Back, Home, etc.)"""
        method_map = {
            "up": "Input.Up",
            "down": "Input.Down",
            "left": "Input.Left",
            "right": "Input.Right",
            "select": "Input.Select",
            "back": "Input.Back",
            "home": "Input.Home",
            "info": "Input.Info",
            "osd": "Input.ShowOSD"
        }
        method = method_map.get(action.lower())
        if method:
            res = await self.send_rpc(method)
            return res is not None
        return False

    async def launch_kodi(self) -> bool:
        """Starts Kodi process on local display if installed."""
        def _launch():
            try:
                # Check if already running
                check = subprocess.run(["pgrep", "-x", "kodi.bin"], capture_output=True)
                if check.returncode == 0:
                    logger.info("Kodi is already running.")
                    return True
                
                # Launch via background subprocess
                cmd = self.config.launch_command.split()
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.info(f"Launched Kodi via command: {self.config.launch_command}")
                return True
            except Exception as e:
                logger.error(f"Failed to launch Kodi: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _launch)

    async def quit_kodi(self) -> bool:
        """Quits Kodi or brings focus back to home dashboard."""
        res = await self.send_rpc("Application.Quit")
        return res is not None
