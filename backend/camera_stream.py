"""
Camera / video doorbell viewing. ffmpeg reads the camera stream (Tuya cloud HLS/RTSP, or a local RTSP URL)
and turns it into a single JPEG or a low-resolution MJPEG feed that a plain <img> tag can show.
Only one live feed runs at a time, and it stops as soon as the browser closes the connection: the Pi is small.
"""
import asyncio
import logging
import shutil
from typing import AsyncIterator, List, Optional, Tuple

logger = logging.getLogger("HomeAuto.Camera")

MAX_LIVE_SECONDS = 300   # a forgotten viewer must not keep a decoder running forever
START_TIMEOUT = 20       # per stream URL: battery doorbells need a few seconds to wake up
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


def _scheme(url: str) -> str:
    return url.split(":", 1)[0].lower()  # never log the URL itself: it carries credentials


def _clean(err: bytes, url: str) -> str:
    """Last part of ffmpeg's error output, with the stream URL (and its credentials) removed."""
    return err.decode(errors="replace").replace(url, "<url>").strip()[-300:]


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

    async def snapshot(self, urls: List[str]) -> Optional[bytes]:
        """One JPEG frame, or None when none of the URLs delivers one in time."""
        for url in urls:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", *_input_args(url), "-an", "-frames:v", "1",
                "-vf", f"scale={WIDTH}:-2", "-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                data, err = await asyncio.wait_for(proc.communicate(), START_TIMEOUT)
                if data:
                    return data
                logger.warning(f"Camera snapshot via {_scheme(url)} gave no picture: {_clean(err, url)}")
            except asyncio.TimeoutError:
                logger.warning(f"Camera snapshot via {_scheme(url)} timed out")
            finally:
                _kill(proc)
        return None

    async def open_live(self, urls: List[str]) -> Optional[Tuple[asyncio.subprocess.Process, bytes]]:
        """Starts the live feed (replacing any running one). Returns (process, first chunk), or None if no URL delivers video."""
        self.stop_live()
        for url in urls:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", *_input_args(url), "-an", "-t", str(MAX_LIVE_SECONDS),
                "-vf", f"fps={LIVE_FPS},scale={WIDTH}:-2", "-q:v", "8",
                "-f", "mpjpeg", "-boundary_tag", BOUNDARY, "pipe:1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                first = await asyncio.wait_for(proc.stdout.read(65536), START_TIMEOUT)
            except asyncio.TimeoutError:
                first = b""
            if first:
                asyncio.ensure_future(proc.stderr.read())  # keep draining the (tiny) error output so ffmpeg never blocks on it
                self._live = proc
                return proc, first
            err = b""
            if proc.returncode is not None:
                err = await proc.stderr.read()
            logger.warning(f"Camera live view via {_scheme(url)} gave no video: {_clean(err, url)}")
            _kill(proc)
        return None

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
