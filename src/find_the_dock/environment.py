import random
import textwrap
import weakref
from collections import deque

from .action import Action
from .state import State


class Environment:
    """A fixed 4x4 grid where a robot navigates to a charging station.

    Start: randomized on reset. Charging station: top-right (0, 3).
    Holes are generated once and remain fixed across episode resets.
    Entering a hole or reaching the charging station ends the episode.
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
        title: str = "Markov Decision Process",
        render: bool = True,
    ) -> None:
        if not isinstance(obstacles, bool):
            raise TypeError("obstacles must be a bool")
        if fps is not None and (type(fps) is not int or fps < 1):
            raise ValueError("fps must be a positive integer or None")

        if not isinstance(title, str):
            raise TypeError("title must be a string")

        self.title = title
        self.fps = fps
        self.start: State | None = None
        self.target = State(0, 3)
        self._rng = random.Random()
        self._obstacles_enabled = obstacles
        self.obstacle_positions: frozenset[tuple[int, int]] = frozenset()
        self._renderer = None
        self._starts: tuple[State, ...] = ()
        self.reset()
        if render:
            from .renderer import Renderer

            self._renderer = Renderer(self.fps)
            weakref.finalize(self, self._renderer.close)
            self._renderer.draw(self)

    def reset(self) -> State:
        """Start a new episode on the same map with a new robot position."""
        if not self._starts:
            # Choose the initial start before placing obstacles.
            self.start = self._rng.choice(
                [
                    State(row, col)
                    for row in range(self.SIZE)
                    for col in range(self.SIZE)
                    if (row, col) != (self.target.row, self.target.col)
                ]
            )
            if self._obstacles_enabled:
                self.obstacle_positions = self._generate_obstacles()
            self._goal_state = State(
                self.target.row, self.target.col, self.obstacle_positions
            )
            self._terminal_states = (self._goal_state,) + tuple(
                State(row, col, self.obstacle_positions)
                for row, col in sorted(self.obstacle_positions)
            )
            # Valid starts have a route to the dock that avoids the holes.
            reachable = {(self.target.row, self.target.col)}
            queue = deque(reachable)
            while queue:
                row, col = queue.popleft()
                for dr, dc in self._MOVES.values():
                    pos = row + dr, col + dc
                    if (
                        0 <= pos[0] < self.SIZE
                        and 0 <= pos[1] < self.SIZE
                        and pos not in self.obstacle_positions
                        and pos not in reachable
                    ):
                        reachable.add(pos)
                        queue.append(pos)
            self._starts = tuple(
                State(row, col, self.obstacle_positions)
                for row, col in sorted(reachable)
                if (row, col) != (self.target.row, self.target.col)
            )
            self.start = next(
                s
                for s in self._starts
                if (s.row, s.col) == (self.start.row, self.start.col)
            )
        else:
            self.start = self._rng.choice(
                tuple(s for s in self._starts if s is not self.start)
            )
        self.state = self.start
        self.steps = 0
        self._success = False
        self._terminated = False
        self._debug_messages: list[str] = []
        if self._renderer is not None:
            self._renderer.draw(self)
        return self.state

    def step(self, action: Action | int) -> tuple[State, float]:
        """Apply an action and return the resulting state and reward."""
        if self._terminated:
            raise RuntimeError("Episode finished. Call reset() before stepping again.")
        if isinstance(action, bool) or not isinstance(action, int):
            raise TypeError("action must be a valid Action")
        try:
            action = Action(action)
        except ValueError:
            raise ValueError("action must be a valid Action") from None

        if self._renderer is not None:
            self._renderer.before_step(self)

        dr, dc = self._MOVES[action]
        row, col = self.state.row + dr, self.state.col + dc

        if not (0 <= row < self.SIZE and 0 <= col < self.SIZE):
            reward = -5.0
        else:
            self.state = State(row, col, self.obstacle_positions)
            reward = -5.0 if (row, col) in self.obstacle_positions else -1.0

        self.steps += 1

        if self.state == self._goal_state:
            self._success = True
            reward = 100.0
        self._terminated = self._success or (
            self.state.row, self.state.col
        ) in self.obstacle_positions

        if self._renderer is not None:
            self._renderer.after_step(self)

        return self.state, reward

    def terminal_states(self) -> list[State]:
        """Return the dock followed by all hole states in coordinate order."""
        return list(self._terminal_states)

    def debug_print(self, message: str) -> None:
        """Replace the on-screen debug text with the latest message."""
        self._debug_messages = [textwrap.dedent(str(message)).strip("\n")]
        if self._renderer is not None:
            self._renderer._update_debug(self._debug_messages[0])

    def _states(self) -> list[State]:
        """Return every grid position, including the dock and terminal holes."""
        return [
            State(row, col, self.obstacle_positions)
            for row in range(self.SIZE)
            for col in range(self.SIZE)
        ]

    def _actions(self) -> list[Action]:
        return Action.all()

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
            if (row, col)
            not in (
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
