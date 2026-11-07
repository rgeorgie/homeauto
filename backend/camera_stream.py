"""
Camera / video doorbell viewing. ffmpeg reads the camera stream (Tuya cloud HLS/RTSP, or a local RTSP URL)
and turns it into a single JPEG or a low-resolution MJPEG feed that a plain <img> tag can show.
Only one live feed runs at a time, and it stops as soon as the browser closes the connection: the Pi is small.
"""
import asyncio
import logging
import shutil
from typing import AsyncIterator, Optional, Tuple

logger = logging.getLogger("HomeAuto.Camera")

MAX_LIVE_SECONDS = 300   # a forgotten viewer must not keep a decoder running forever
START_TIMEOUT = 30       # battery doorbells need a few seconds to wake up
STALL_TIMEOUT = 15       # no data for this long: the stream is dead
LIVE_FPS = 6
WIDTH = 640

BOUNDARY = "frame"
LIVE_MEDIA_TYPE = f"multipart/x-mixed-replace;boundary={BOUNDARY}"


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _input_args(url: str):
    args = ["-loglevel", "error"]
    if url.lower().startswith("rtsp"):
        args += ["-rtsp_transport", "tcp"]
    return args + ["-i", url]


def _kill(proc: asyncio.subprocess.Process):
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    asyncio.ensure_future(proc.wait())  # reap it


class CameraStreamer:
    def __init__(self):
        self._live: Optional[asyncio.subprocess.Process] = None

    def stop_live(self):
        proc, self._live = self._live, None
        if proc:
            _kill(proc)

    async def snapshot(self, url: str) -> Optional[bytes]:
        """One JPEG frame, or None when the camera does not deliver one in time."""
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", *_input_args(url), "-an", "-frames:v", "1",
            "-vf", f"scale={WIDTH}:-2", "-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            data, _ = await asyncio.wait_for(proc.communicate(), START_TIMEOUT)
            return data or None
        except asyncio.TimeoutError:
            logger.warning("Camera snapshot timed out")
            return None
        finally:
            _kill(proc)

    async def open_live(self, url: str) -> Optional[Tuple[asyncio.subprocess.Process, bytes]]:
        """Starts the live feed (replacing any running one). Returns (process, first chunk), or None if no video arrives."""
        self.stop_live()
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", *_input_args(url), "-an", "-t", str(MAX_LIVE_SECONDS),
            "-vf", f"fps={LIVE_FPS},scale={WIDTH}:-2", "-q:v", "8",
            "-f", "mpjpeg", "-boundary_tag", BOUNDARY, "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            first = await asyncio.wait_for(proc.stdout.read(65536), START_TIMEOUT)
        except asyncio.TimeoutError:
            first = b""
        if not first:
            _kill(proc)
            return None
        self._live = proc
        return proc, first

    async def iter_live(self, proc: asyncio.subprocess.Process, first: bytes) -> AsyncIterator[bytes]:
        try:
            yield first
            while True:
                chunk = await asyncio.wait_for(proc.stdout.read(65536), STALL_TIMEOUT)
                if not chunk:
                    break
                yield chunk
        except asyncio.TimeoutError:
            pass
        finally:  # also reached when the browser disconnects
            if self._live is proc:
                self._live = None
            _kill(proc)


streamer = CameraStreamer()
