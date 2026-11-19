"""Private browser renderer. Environment keeps ownership of server and controls."""

import asyncio
import json
import threading
import time
import webbrowser
from pathlib import Path

from aiohttp import WSMsgType, web


_PROJECT = Path(__file__).resolve().parents[2]
_WEB = _PROJECT / "web"
_ASSETS = _PROJECT / "assets"


class Renderer:
    """Host the Phaser UI locally without exposing networking to the RL algorithm."""

    DISPLAY_INTERVAL = 1 / 30

    def __init__(self, fps: int | None) -> None:
        self.fps = fps
        self._timed_fps = fps if fps is not None else 10
        self.playing = True
        self._steps_requested = 0
        self._manual_step = False
        self._step_started = 0.0

        self._condition = threading.Condition()
        self._closed_event = threading.Event()
        self._ready = threading.Event()
        self._closed = False
        self._startup_error: Exception | None = None
        self._latest_state: dict | None = None
        self._revision = 0
        self._last_publish = 0.0

        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._broadcast_task: asyncio.Task | None = None
        self._clients: set[web.WebSocketResponse] = set()
        self._port: int | None = None

        self._thread = threading.Thread(
            target=self._run_server, name="robot-browser-ui", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=10) or self._startup_error:
            raise RuntimeError("Could not start the robot UI server") from self._startup_error

        url = f"http://127.0.0.1:{self._port}/"
        if not webbrowser.open(url):
            print(f"Open the robot simulator in a browser: {url}")

    def _run_server(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._start_server())
            self._ready.set()
            loop.run_forever()
        except Exception as exc:
            self._startup_error = exc
            self._ready.set()
        finally:
            try:
                loop.run_until_complete(self._stop_server())
            finally:
                loop.close()

    async def _start_server(self) -> None:
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/app.js", self._script)
        app.router.add_get("/style.css", self._style)
        app.router.add_get("/ws", self._websocket)
        app.router.add_static("/assets/", _ASSETS, show_index=False)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self._port = site._server.sockets[0].getsockname()[1]
        self._broadcast_task = asyncio.create_task(self._broadcast())

    async def _stop_server(self) -> None:
        if self._broadcast_task is not None:
            self._broadcast_task.cancel()
            await asyncio.gather(self._broadcast_task, return_exceptions=True)
        for ws in tuple(self._clients):
            await ws.close()
        if self._runner is not None:
            await self._runner.cleanup()

    async def _index(self, request: web.Request) -> web.FileResponse:
        return web.FileResponse(_WEB / "index.html")

    async def _script(self, request: web.Request) -> web.FileResponse:
        return web.FileResponse(_WEB / "app.js")

    async def _style(self, request: web.Request) -> web.FileResponse:
        return web.FileResponse(_WEB / "style.css")

    async def _websocket(self, request: web.Request) -> web.WebSocketResponse:
        # Only the locally served page may control the simulator.
        origin = request.headers.get("Origin")
        if origin not in (None, f"http://127.0.0.1:{self._port}"):
            raise web.HTTPForbidden()

        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self._clients.add(ws)

        with self._condition:
            state = self._latest_state
        if state is not None:
            await ws.send_json(state)

        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(message.data)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and data.get("type") == "control":
                    self._handle_control(data.get("command"))
        finally:
            self._clients.discard(ws)
            # Allow a normal page reload to reconnect before considering it closed.
            await asyncio.sleep(1)
            if not self._clients and not self._closed:
                self._mark_closed()
        return ws

    async def _broadcast(self) -> None:
        previous_revision = -1
        while True:
            await asyncio.sleep(self.DISPLAY_INTERVAL)
            with self._condition:
                revision = self._revision
                state = self._latest_state
            if revision == previous_revision or state is None or not self._clients:
                continue
            previous_revision = revision
            await self._send_now(state)

    async def _send_now(self, state: dict) -> None:
        """Send an exact snapshot instead of waiting for the next display tick."""
        for ws in tuple(self._clients):
            try:
                await ws.send_json(state)
            except (ConnectionError, RuntimeError):
                self._clients.discard(ws)

    def _handle_control(self, command: str | None) -> None:
        with self._condition:
            finished = bool(
                self._latest_state
                and (self._latest_state["success"] or self._latest_state["truncated"])
            )
            if command == "toggle_play" and not finished:
                self.playing = not self.playing
                self._steps_requested = 0
            elif command == "step" and not finished and not self.playing:
                self._steps_requested += 1
            elif command == "fps_down" and self.fps is not None:
                self.fps = max(1, self.fps - 1)
                self._timed_fps = self.fps
            elif command == "fps_up" and self.fps is not None:
                if self.fps < 60:
                    self.fps += 1
                self._timed_fps = self.fps
            elif command == "fps_toggle":
                self.fps = self._timed_fps if self.fps is None else None
            else:
                return

            if self._latest_state is not None:
                self._latest_state = {
                    **self._latest_state, "fps": self.fps, "playing": self.playing
                }
                self._revision += 1
            self._condition.notify_all()

    def draw(self, env, *, force: bool = False) -> None:
        """Publish snapshots at display speed, except for manual steps and resets."""
        env.fps = self.fps
        now = time.perf_counter()
        with self._condition:
            previous = self._latest_state
            paused = not self.playing
        just_finished = (env._success or env._truncated) and not (
            previous and (previous["success"] or previous["truncated"])
        )
        new_episode = paused and env.steps == 0 and previous and previous["steps"] != 0
        if (
            not force
            and not just_finished
            and not new_episode
            and now - self._last_publish < self.DISPLAY_INTERVAL
        ):
            return
        self._last_publish = now
        state = {
            "type": "state",
            "robot": [env.state.row, env.state.col],
            "dock": [env.target.row, env.target.col],
            "obstacles": [list(pos) for pos in sorted(env.obstacle_positions)],
            "steps": env.steps,
            "success": env._success,
            "truncated": env._truncated,
            "debug": "\n".join(env._debug_messages),
        }
        with self._condition:
            snapshot = {**state, "fps": self.fps, "playing": self.playing}
            self._latest_state = snapshot
            self._revision += 1

        # A manual Step must reach Phaser even if an episode resets
        # before the regular 30 Hz broadcaster wakes up.
        loop = getattr(self, "_loop", None)
        if force and loop is not None and loop.is_running():
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._send_now(snapshot))
            )

    def before_step(self, env) -> None:
        """Block while paused, consuming at most one Step request per action."""
        if not self.playing:
            self.draw(env, force=True)
        with self._condition:
            while not self._closed:
                if self.playing:
                    self._manual_step = False
                    env.fps = self.fps
                    self._step_started = time.perf_counter()
                    return
                if self._steps_requested:
                    self._steps_requested -= 1
                    self._manual_step = True
                    env.fps = self.fps
                    self._step_started = time.perf_counter()
                    return
                self._condition.wait()
        raise RuntimeError("Simulator browser closed")

    def after_step(self, env) -> None:
        """Always publish a manual Step; throttle automatic playback only."""
        with self._condition:
            manual = self._manual_step
        self.draw(env, force=manual)
        if manual:
            return
        with self._condition:
            while not self._closed and self.fps is not None:
                remaining = self._step_started + 1 / self.fps - time.perf_counter()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)

    def wait_until_closed(self, env) -> None:
        """Keep the local UI available until its browser tab is closed."""
        self.draw(env)
        self._closed_event.wait()

    def _mark_closed(self) -> None:
        with self._condition:
            self._closed = True
            self._closed_event.set()
            self._condition.notify_all()

    def close(self) -> None:
        if self._closed_event.is_set() and not self._thread.is_alive():
            return
        self._mark_closed()
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=3)
