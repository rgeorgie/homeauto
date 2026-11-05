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
        self.last_error = ""
        self.own_port = 0  # HomeAuto's own HTTP port, set by main.py so Kodi is never pointed at ourselves
        self._update_url()

    def _update_url(self):
        self.rpc_url = f"http://{self.config.host}:{self.config.port}/jsonrpc"
        self.auth = (self.config.user, self.config.password) if self.config.user else None

    def reload_config(self, config: KodiConfig):
        self.config = config
        self._update_url()
        logger.info("KodiManager configuration reloaded.")

    async def test_connection(self, host: str, port: int, user: str = "", password: str = "") -> Dict[str, Any]:
        """Tests connection to Kodi JSON-RPC."""
        test_url = f"http://{host}:{port}/jsonrpc"
        auth = (user, password) if user else None
        payload = {"jsonrpc": "2.0", "method": "JSONRPC.Ping", "id": 1}

        def _ping():
            try:
                res = requests.post(test_url, json=payload, auth=auth, timeout=3)
                if res.status_code == 200 and res.json().get("result") == "pong":
                    return {"success": True}
                return {"success": False, "error": f"HTTP {res.status_code}: {res.text}"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _ping)

    async def send_rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Sends a JSON-RPC request to Kodi."""
        if not self.config.enabled:
            self.last_error = "Kodi integration is disabled in Settings"
            return None

        # Never query the HomeAuto server itself (it also answers /jsonrpc with "pong")
        if self.config.host in ["127.0.0.1", "localhost"] and self.own_port and self.config.port == self.own_port:
            msg = f"Kodi port {self.config.port} is HomeAuto's own port. Set Kodi's web server port in Settings (e.g. 8080)"
            if self.last_error != msg:  # log once, not on every 3s status poll
                logger.warning(msg)
            self.last_error = msg
            return None

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": 1
        }
        if params is not None:
            payload["params"] = params

        def _request():
            try:
                res = requests.post(self.rpc_url, json=payload, auth=self.auth, timeout=1.5)
                if res.status_code == 200:
                    data = res.json()
                    if "error" in data:
                        self.last_error = f"Kodi rejected {method}: {data['error'].get('message', data['error'])}"
                        return None
                    # HomeAuto's own /jsonrpc catch-all answers "pong" to everything; real Kodi never does for these methods
                    if data.get("result") == "pong" and method != "JSONRPC.Ping":
                        self.last_error = f"{self.rpc_url} is HomeAuto itself, not Kodi. Fix the Kodi host/port in Settings"
                        return None
                    self.last_error = ""
                    return data.get("result")
                self.last_error = f"Kodi HTTP {res.status_code} at {self.rpc_url} (check username/password)"
            except Exception as e:
                self.last_error = f"HomeAuto server cannot reach Kodi at {self.config.host}:{self.config.port} (is Kodi running with its web server enabled?)"
                logger.debug(f"Kodi JSON-RPC request error ({method}): {e}")
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

        if not isinstance(players, list) or not players:
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
        """Sends GUI input actions (Up, Down, Left, Right, Select, Back, Home, Menu, etc.)"""
        method_map = {
            "up": "Input.Up",
            "down": "Input.Down",
            "left": "Input.Left",
            "right": "Input.Right",
            "select": "Input.Select",
            "ok": "Input.Select",
            "back": "Input.Back",
            "home": "Input.Home",
            "info": "Input.Info",
            "osd": "Input.ShowOSD",
            "menu": "Input.ContextMenu",
            "contextmenu": "Input.ContextMenu"
        }
        method = method_map.get(action.lower())
        if method:
            res = await self.send_rpc(method)
            return res == "OK" or res is not None
        return False

    KODI_PROCESS_NAMES = ["kodi", "kodi.bin", "kodi-x11", "kodi-wayland", "kodi-gbm", "kodi-standalone"]

    def _kodi_running(self) -> bool:
        return any(subprocess.run(["pgrep", "-x", n], capture_output=True).returncode == 0 for n in self.KODI_PROCESS_NAMES)

    def _ping_sync(self) -> bool:
        try:
            res = requests.post(self.rpc_url, json={"jsonrpc": "2.0", "method": "JSONRPC.Ping", "id": 1}, auth=self.auth, timeout=1.5)
            return res.status_code == 200 and res.json().get("result") == "pong"
        except Exception:
            return False

    async def launch_kodi(self) -> bool:
        """Starts Kodi on the local display, then verifies its JSON-RPC web server answers. Sets last_error on failure."""
        def _launch():
            import os, time
            try:
                if not self._kodi_running():
                    env = os.environ.copy()
                    env.setdefault("DISPLAY", ":0")
                    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
                    if "WAYLAND_DISPLAY" not in env and os.path.exists(f"{env['XDG_RUNTIME_DIR']}/wayland-0"):
                        env["WAYLAND_DISPLAY"] = "wayland-0"
                    log_path = "/tmp/homeauto-kodi.log"
                    with open(log_path, "ab") as log:
                        subprocess.Popen(self.config.launch_command.split(), stdout=log, stderr=log, env=env, start_new_session=True)
                    logger.info(f"Launched Kodi via command: {self.config.launch_command} (output: {log_path})")

                # Wait for Kodi's web server (startup can take a while on a Pi)
                for _ in range(20):
                    if self._ping_sync():
                        self.last_error = ""
                        return True
                    time.sleep(1)

                if self._kodi_running():
                    self.last_error = (f"Kodi is running but its web server does not answer at {self.config.host}:{self.config.port}. "
                                       "In Kodi: Settings > Services > Control > enable 'Allow remote control via HTTP' and match the port/username/password in HomeAuto Settings")
                else:
                    self.last_error = f"Kodi did not start with '{self.config.launch_command}'. See /tmp/homeauto-kodi.log on the HomeAuto device"
                logger.warning(self.last_error)
                return False
            except Exception as e:
                self.last_error = f"Failed to launch Kodi: {e}"
                logger.error(self.last_error)
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _launch)

    async def quit_kodi(self) -> bool:
        """Quits Kodi or brings focus back to home dashboard."""
        res = await self.send_rpc("Application.Quit")
        return res is not None
