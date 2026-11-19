import random
import textwrap
from collections import deque

from .action import Action
from .state import State


class Environment:
    """A fixed 4x4 grid where a robot navigates to a charging station.

    Start: randomized on reset. Charging station: top-right (0, 3).
    Obstacles are generated once and remain fixed across episode resets.
    """

    SIZE = 4
    _MOVES = {
        Action.UP: (-1, 0),
        Action.DOWN: (1, 0),
        Action.LEFT: (0, -1),
        Action.RIGHT: (0, 1),
    }

    def __init__(
        self,
        obstacles: bool = False,
        fps: int | None = 10,
        max_steps: int | None = None,
        seed: int | None = None,
        render: bool = True,
    ) -> None:
        if not isinstance(obstacles, bool):
            raise TypeError("obstacles must be a bool")
        if fps is not None and (type(fps) is not int or fps < 1):
            raise ValueError("fps must be a positive integer or None")
        if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
            raise ValueError("max_steps must be a positive integer or None")

        self.fps = fps
        self.max_steps = max_steps
        self.start: State | None = None
        self.target = State(0, 3)
        self._rng = random.Random(seed)
        self._obstacles_enabled = obstacles
        self.obstacle_positions: frozenset[tuple[int, int]] = frozenset()
        self._renderer = None
        self.reset()
        if render:
            from .renderer import Renderer

            self._renderer = Renderer(self.fps)
            self._renderer.draw(self)

    def states(self) -> list[State]:
        """Return every traversable position, including the terminal state."""
        return [
            State(row, col, self.obstacle_positions)
            for row in range(self.SIZE)
            for col in range(self.SIZE)
            if (row, col) not in self.obstacle_positions
        ]

    def actions(self) -> list[Action]:
        return Action.all()

    def reset(self) -> State:
        """Start a new episode on the same map with a new robot position."""
        candidates = [
            State(row, col)
            for row in range(self.SIZE)
            for col in range(self.SIZE)
            if (row, col) != (self.target.row, self.target.col)
            and (row, col) not in self.obstacle_positions
            and (self.start is None or (row, col) != (self.start.row, self.start.col))
            and self._path_exists(self.obstacle_positions, (row, col))
        ]
        self.start = self._rng.choice(candidates)
        if self._obstacles_enabled and not self.obstacle_positions:
            self.obstacle_positions = self._generate_obstacles()
        self.state = State(self.start.row, self.start.col, self.obstacle_positions)
        self.steps = 0
        self._success = False
        self._truncated = False
        self._debug_messages: list[str] = []
        if self._renderer is not None:
            self._renderer.draw(self)
        return self.state

    def step(self, action: Action | int) -> tuple[State, float]:
        """Apply an action and return the resulting state and reward."""
        if self._success or self._truncated:
            raise RuntimeError("Episode finished. Call reset() before stepping again.")
        if isinstance(action, bool) or not isinstance(action, int):
            raise TypeError("action must be a valid Action")
        try:
            action = Action(action)
        except ValueError:
            raise ValueError("action must be a valid Action") from None

        if self._renderer is not None:
            self._renderer.before_step(self)

        next_state = self._move(self.state, action)

        if (
            not self._within_grid(next_state)
            or (next_state.row, next_state.col) in self.obstacle_positions
        ):
            reward = -5.0
        else:
            self.state = next_state
            reward = -1.0

        self.steps += 1

        if self.state == self.terminal():
            self._success = True
            reward = 100.0
        elif self.max_steps is not None and self.steps >= self.max_steps:
            self._truncated = True

        if self._renderer is not None:
            self._renderer.after_step(self)

        return self.state, reward

    def terminal(self) -> State:
        """Return the terminal goal state (the charging station)."""
        return State(self.target.row, self.target.col, self.obstacle_positions)

    def print(self, message: str) -> None:
        """Replace the on-screen debug text with the latest message."""
        self._debug_messages = [textwrap.dedent(str(message)).strip("\n")]

    def wait_until_closed(self) -> None:
        """Keep the completed simulation visible until its window is closed."""
        if self._renderer is not None:
            self._renderer.wait_until_closed(self)

    def close(self) -> None:
        """Stop the private browser renderer, if one was started."""
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None

    def _within_grid(self, state: State) -> bool:
        return 0 <= state.row < self.SIZE and 0 <= state.col < self.SIZE

    def _move(self, state: State, action: Action) -> State:
        row_delta, col_delta = self._MOVES[action]
        return State(
            state.row + row_delta,
            state.col + col_delta,
            state.obstacles,
        )

    def _generate_obstacles(self) -> frozenset[tuple[int, int]]:
        candidates = [
            (row, col)
            for row in range(self.SIZE)
            for col in range(self.SIZE)
            if (row, col) not in (
                (self.start.row, self.start.col),
                (self.target.row, self.target.col),
            )
        ]

        while True:
            blocked = frozenset(self._rng.sample(candidates, 2))
            if blocked != self.obstacle_positions and self._path_exists(blocked):
                return blocked

    def _path_exists(
        self,
        blocked: frozenset[tuple[int, int]],
        start: tuple[int, int] | None = None,
    ) -> bool:
        """Check that the robot can still reach the charger."""
        if start is None:
            start = (self.start.row, self.start.col)
        target = (self.target.row, self.target.col)
        queue = deque([start])
        visited = {start}

        while queue:
            current = queue.popleft()
            if current == target:
                return True

            for row_delta, col_delta in self._MOVES.values():
                neighbor = (current[0] + row_delta, current[1] + col_delta)
                if (
                    0 <= neighbor[0] < self.SIZE
                    and 0 <= neighbor[1] < self.SIZE
                    and neighbor not in blocked
                    and neighbor not in visited
                ):
                    visited.add(neighbor)
                    queue.append(neighbor)

        return False
