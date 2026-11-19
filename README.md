# Find the Dock

A small **4×4 reinforcement-learning environment** in Python with an optional Phaser 3 browser visualization. The environment remains independent of Gymnasium.

## Installation

From the project root:

```bash
pdm install
```

Phaser 3.90 is loaded from a CDN when the browser page opens, so the first browser launch needs internet access. The Python side requires only `aiohttp`; no Node.js, npm, or frontend build step is necessary.

## Usage

```python
from find_the_dock import Action, Environment

env = Environment(obstacles=True, fps=30, seed=42)

state = env.reset()
env.print(f"Initial state: {state}")

state, reward = env.step(Action.UP)
```

Constructing `Environment(..., render=True)` automatically launches the local visualization server and opens a browser tab. **The learning algorithm does not need to create or manage the server or WebSocket.** It uses the same `reset()`, `step()`, `terminal()`, and `print()` methods as before.

For headless training:

```python
env = Environment(obstacles=True, render=False)
```

This skips the browser and networking entirely.

## Browser controls

The Phaser UI uses the same 1120×1060 dark design with rounded grid cells, a robot sprite, charging dock, two obstacles, debug panel, and control sidebar.

- **Play/Pause:** pauses or resumes Python simulation steps.
- **Step:** permits exactly one agent-selected action while paused and immediately publishes its resulting state to the browser.
- **FPS −/+ :** adjusts timed stepping from 1 to 60 FPS; an FPS passed in code above 60 remains valid.
- **None:** toggles between unrestricted execution and the most recently selected positive FPS (defaulting to 10 when constructed with `fps=None`).
- **Debug output:** `env.print(text)` replaces the previous message and is shown in the browser.

Timing and simulation state are controlled in Python. The browser sends only control commands and receives state snapshots. During automatic playback, snapshots are limited to about 30 per second, independent of how many Python steps execute. Manual Step updates bypass this limit. `fps=None` introduces no timing delay. Closing the browser tab stops an active rendered simulation; `env.close()` stops the internal server.

The private server binds only to `127.0.0.1` on an automatically chosen port.

## Environment rules

- Grid coordinates are zero-based in a fixed **4×4** grid.
- The charging dock stays at `(0, 3)`.
- The robot starts from a different reachable unoccupied cell on every `reset()`.
- `obstacles=True` creates two obstacles **once per Environment instance**. The same obstacles persist across episode resets and cannot overlap the dock or the robot's starting cell.
- The `seed` parameter makes generation reproducible.
- `step(action)` returns `(State, reward)`; valid movement is **−1**, wall/obstacle collisions are **−5**, and arriving at the dock is **+100**.
- Calling `step()` after the goal or the configured `max_steps` limit raises `RuntimeError` until `reset()`.
- `terminal()` returns the terminal `State`, including current obstacle positions.
- `State(row, col, obstacles)` is immutable and hashable and includes the full obstacle layout.
- `Action` is an `IntEnum`: `UP=0`, `DOWN=1`, `LEFT=2`, `RIGHT=3`.

## Run the Monte Carlo example

```bash
pdm run example
```

## Tests

```bash
pdm run test
```
