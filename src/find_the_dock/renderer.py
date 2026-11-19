"""Private browser renderer. Environment keeps ownership of server and controls."""

import asyncio
import json
import threading
import time
import webbrowser
from pathlib import Path

from aiohttp import WSMsgType, web

_WEB = Path(__file__).resolve().parent / "web"


class Renderer:
    """Host the Phaser UI locally without exposing networking to the RL algorithm."""

    DISPLAY_FPS = 60
    DISPLAY_INTERVAL = 1 / DISPLAY_FPS
    TERMINAL_HOLD_SECONDS = 0.18
    START_HOLD_SECONDS = 0.18

    def __init__(self, fps: int | None) -> None:
        self.fps = fps
        self._timed_fps = fps if fps is not None else 10
        self.playing = False
        self._steps_requested = 0
        self._manual_step = False
        self._step_started = 0.0
        self._start_visible_until = 0.0

        self._condition = threading.Condition()
        self._closed_event = threading.Event()
        self._ready = threading.Event()
        self._closed = False
        self._startup_error: Exception | None = None
        self._latest_state: dict | None = None
        self._revision = 0

        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._broadcast_task: asyncio.Task | None = None
        self._clients: set[web.WebSocketResponse] = set()
        self._port: int | None = None
        self._client_queues: dict[web.WebSocketResponse, asyncio.Queue] = {}
        self._client_tasks: dict[web.WebSocketResponse, asyncio.Task] = {}
        self._publish_event: asyncio.Event | None = None
        self._sent_revision = -1
        self._disconnect_handle: asyncio.TimerHandle | None = None
        self._page_loading_until = 0.0

        self._thread = threading.Thread(
            target=self._run_server, name="robot-browser-ui", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=10):
            self.close()
            raise RuntimeError("Robot UI server startup timed out")
        if self._startup_error is not None:
            raise RuntimeError(
                f"Could not start the robot UI server: {self._startup_error}"
            ) from self._startup_error

        url = f"http://127.0.0.1:{self._port}/"
        try:
            if not webbrowser.open(url):
                print(f"Open the robot simulator in a browser: {url}")
        except Exception:
            self.close()
            raise

        print(f"Simulator browser opened: {url}")

    def _run_server(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._start_server())
            self._ready.set()
            if not self._closed:
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
        self._publish_event = asyncio.Event()
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/app.js", self._script)
        app.router.add_get("/style.css", self._style)
        app.router.add_get("/ws", self._websocket)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self._port = site._server.sockets[0].getsockname()[1]
        self._broadcast_task = asyncio.create_task(self._broadcast())

    async def _stop_server(self) -> None:
        if self._disconnect_handle is not None:
            self._disconnect_handle.cancel()
        tasks = tuple(self._client_tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._broadcast_task is not None:
            self._broadcast_task.cancel()
            await asyncio.gather(self._broadcast_task, return_exceptions=True)
        for ws in tuple(self._clients):
            await ws.close()
        if self._runner is not None:
            await self._runner.cleanup()

    async def _index(self, request: web.Request) -> web.FileResponse:
        # A reload has begun; allow time for Phaser to load before its socket opens.
        self._page_loading_until = time.monotonic() + 30
        self._schedule_disconnect()
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

        if self._closed:
            raise web.HTTPServiceUnavailable()
        ws = web.WebSocketResponse(heartbeat=30, timeout=1)
        await ws.prepare(request)
        self._clients.add(ws)
        self._page_loading_until = 0.0
        if self._disconnect_handle is not None:
            self._disconnect_handle.cancel()
        queue = asyncio.Queue(maxsize=64)
        self._client_queues[ws] = queue
        sender = asyncio.create_task(self._send_client(ws, queue))
        self._client_tasks[ws] = sender

        with self._condition:
            state = self._latest_state
        if state is not None:
            queue.put_nowait(json.dumps(state))

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
            self._client_queues.pop(ws, None)
            self._client_tasks.pop(ws, None)
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            self._schedule_disconnect()
        return ws

    def _schedule_disconnect(self) -> None:
        if self._disconnect_handle is not None:
            self._disconnect_handle.cancel()
        if not self._clients and not self._closed:
            delay = max(1.0, self._page_loading_until - time.monotonic())
            self._disconnect_handle = self._loop.call_later(delay, self._mark_closed)

    async def _send_client(self, ws, queue) -> None:
        try:
            while True:
                payload = await queue.get()
                await asyncio.wait_for(ws.send_str(payload), timeout=5)
        except (ConnectionError, RuntimeError, TimeoutError):
            pass
        finally:
            await ws.close()

    def _queue_snapshot(self, state: dict, revision: int) -> None:
        # This runs only on the server loop. Each client has an independent,
        # bounded sender so a stalled tab cannot block the other tabs.
        if revision <= self._sent_revision:
            return
        self._sent_revision = revision
        if not self._client_queues:
            return
        payload = json.dumps(state)
        for ws, queue in tuple(self._client_queues.items()):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                self._client_queues.pop(ws, None)
                self._client_tasks[ws].cancel()

    async def _broadcast(self) -> None:
        last_send = 0.0
        while True:
            await self._publish_event.wait()
            self._publish_event.clear()
            delay = self.DISPLAY_INTERVAL - (time.perf_counter() - last_send)
            if delay > 0:
                await asyncio.sleep(delay)
            with self._condition:
                revision, state = self._revision, self._latest_state
            if state is not None and revision > self._sent_revision:
                self._queue_snapshot(state, revision)
                last_send = time.perf_counter()

    def _publish(self, state: dict, revision: int, force: bool) -> None:
        if self._closed:
            return
        if force:
            self._queue_snapshot(state, revision)
        else:
            self._publish_event.set()

    def _notify_snapshot(self, *, force: bool = False) -> None:
        loop = getattr(self, "_loop", None)
        if loop is None or not loop.is_running():
            return
        with self._condition:
            state, revision = self._latest_state, self._revision
        try:
            loop.call_soon_threadsafe(self._publish, state, revision, force)
        except RuntimeError:
            if not self._closed:
                raise

    def _update_debug(self, message: str) -> None:
        with self._condition:
            if self._latest_state is None or self._latest_state["debug"] == message:
                return
            self._latest_state = {**self._latest_state, "debug": message}
            self._revision += 1
        self._notify_snapshot()

    def _handle_control(self, command: str | None) -> None:
        with self._condition:
            finished = bool(self._latest_state and self._latest_state["finished"])
            if command == "toggle_play":
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
                    **self._latest_state,
                    "fps": self.fps,
                    "playing": self.playing,
                }
                self._revision += 1
            self._condition.notify_all()
        self._notify_snapshot()

    def draw(self, env, *, force: bool = False) -> None:
        """Stage the latest state; forced snapshots bypass display throttling."""
        env.fps = self.fps
        state = {
            "type": "state",
            "title": env.title,
            "robot": [env.state.row, env.state.col],
            "dock": [env.target.row, env.target.col],
            "obstacles": [list(pos) for pos in sorted(env.obstacle_positions)],
            "steps": env.steps,
            "success": env._success,
            "finished": env._terminated,
            "debug": "\n".join(env._debug_messages),
        }
        with self._condition:
            snapshot = {**state, "fps": self.fps, "playing": self.playing}
            if snapshot == self._latest_state:
                return
            previous = self._latest_state
            new_start = env.steps == 0 and (
                previous is None
                or previous["steps"] != 0
                or previous["robot"] != snapshot["robot"]
            )
            if new_start:
                # Do not let the first action overwrite the spawn before it is drawn.
                self._start_visible_until = (
                    time.perf_counter() + self.START_HOLD_SECONDS
                )
            self._latest_state = snapshot
            self._revision += 1

        self._notify_snapshot(force=force or new_start)

    def before_step(self, env) -> None:
        """Block while paused, consuming at most one Step request per action."""
        if not self.playing:
            self.draw(env, force=True)
        with self._condition:
            while not self._closed:
                if self.playing or self._steps_requested:
                    remaining = self._start_visible_until - time.perf_counter()
                    if remaining > 0:
                        self._condition.wait(timeout=remaining)
                        continue
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
        """Pace playback and keep dock arrivals and hole entries visible."""
        with self._condition:
            manual = self._manual_step
        self.draw(env, force=manual or env._terminated)

        # A terminal episode would otherwise reset before the browser can
        # display its final state. This hold affects rendering, not rewards.
        terminal_deadline = (
            time.perf_counter() + self.TERMINAL_HOLD_SECONDS if env._terminated else 0
        )
        if manual and not env._terminated:
            return

        with self._condition:
            while not self._closed:
                deadline = terminal_deadline
                if not manual:
                    effective_fps = self.DISPLAY_FPS if self.fps is None else self.fps
                    deadline = max(deadline, self._step_started + 1 / effective_fps)
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)

    def wait_until_closed(self, env) -> None:
        """Keep the local UI available until its browser tab is closed."""
        self.draw(env)
        self._closed_event.wait()

    def _mark_closed(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._closed_event.set()
            self._condition.notify_all()
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def close(self) -> None:
        if self._closed_event.is_set() and not self._thread.is_alive():
            return
        self._mark_closed()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=3)
