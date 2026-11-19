import unittest
from unittest.mock import Mock

from src.find_the_dock import Action, Environment, State


class EnvironmentTests(unittest.TestCase):
    def test_grid_and_actions(self):
        env = Environment(obstacles=False, render=False)
        self.assertEqual(len(env._states()), 16)
        self.assertEqual(env._actions(), Action.all())
        previous_start = env.start
        state = env.reset()
        self.assertEqual((state.row, state.col), (env.start.row, env.start.col))
        self.assertNotEqual(env.start, previous_start)
        self.assertNotEqual((state.row, state.col), (env.target.row, env.target.col))
        self.assertEqual(
            {Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT}, set(env._actions())
        )
        self.assertEqual({State(0, 0): 1}[State(0, 0)], 1)
        self.assertEqual(env.terminal_states(), [State(0, 3)])

    def test_state_is_immutable_and_hashable(self):
        state = State(1, 2, frozenset({(0, 0)}))
        self.assertEqual({state: "value"}[State(1, 2, {(0, 0)})], "value")
        with self.assertRaises(AttributeError):
            state.row = 3
        with self.assertRaises(AttributeError):
            del state.col

    def test_action_helpers(self):
        self.assertEqual([a.value for a in Action.all()], [0, 1, 2, 3])
        self.assertTrue(all(isinstance(a, Action) for a in Action.all()))
        self.assertEqual(
            [a.name for a in Action.all()], ["UP", "DOWN", "LEFT", "RIGHT"]
        )
        self.assertEqual(Action(0), Action.UP)
        with self.assertRaises(ValueError):
            Action(9)

    def test_valid_movement_and_collision(self):
        env = Environment(obstacles=False, render=False)
        env.state = State(3, 0)
        self.assertEqual(env.step(Action.RIGHT), (State(3, 1), -1.0))
        self.assertEqual(env.step(Action.DOWN), (State(3, 1), -5.0))
        self.assertEqual(env.step(Action.LEFT), (State(3, 0), -1.0))
        self.assertEqual(env.step(Action.LEFT), (State(3, 0), -5.0))
        self.assertNotIn(env.state, env.terminal_states())

    def test_state_keeps_layout_across_actions(self):
        env = Environment(obstacles=True, render=False)
        layout = env.obstacle_positions
        next_state, _ = env.step(Action.UP)
        self.assertEqual(next_state.obstacles, layout)
        self.assertEqual(env.state.obstacles, layout)

    def test_integer_action_compatibility(self):
        env = Environment(obstacles=False, render=False)
        env.state = State(3, 0)
        self.assertEqual(env.step(3), (State(3, 1), -1.0))

    def test_goal_is_terminal(self):
        env = Environment(obstacles=False, render=False)
        env.state = State(0, 2)
        self.assertEqual(env.step(Action.RIGHT), (State(0, 3), 100.0))
        self.assertEqual(env.state, env.terminal_states()[0])
        self.assertTrue(env._success)
        self.assertTrue(env._terminated)
        with self.assertRaises(RuntimeError):
            env.step(Action.LEFT)
        previous_start = env.start
        state = env.reset()
        self.assertEqual((state.row, state.col), (env.start.row, env.start.col))
        self.assertNotEqual(env.start, previous_start)
        self.assertNotEqual((state.row, state.col), (env.target.row, env.target.col))
        self.assertNotIn(env.state, env.terminal_states())

    def test_no_implicit_step_limit(self):
        env = Environment(obstacles=False, render=False)
        env.state = State(3, 0)

        for _ in range(3):
            self.assertEqual(env.step(Action.DOWN), (State(3, 0), -5.0))

        self.assertEqual(env.steps, 3)
        self.assertFalse(env._success)
        self.assertNotIn(env.state, env.terminal_states())

    def test_obstacles_stay_fixed_between_episodes_and_are_in_state(self):
        env = Environment(obstacles=True, render=False)
        other = Environment(obstacles=True, render=False)
        layout = env.obstacle_positions
        self.assertEqual(len(layout), 2)
        self.assertEqual(len(other.obstacle_positions), 2)
        self.assertEqual(len(env._states()), 16)
        self.assertNotIn((env.start.row, env.start.col), layout)
        self.assertNotIn((env.target.row, env.target.col), layout)
        self.assertTrue(env._path_exists(layout))
        self.assertEqual(env.state.obstacles, layout)

        expected_terminal_states = [State(0, 3, layout)] + [
            State(row, col, layout) for row, col in sorted(layout)
        ]
        self.assertEqual(env.terminal_states(), expected_terminal_states)
        self.assertNotIn(env.start, expected_terminal_states)
        self.assertTrue(all(state.obstacles == layout for state in env._states()))

        previous_start = env.start
        new_state = env.reset()
        self.assertNotEqual(new_state, previous_start)
        self.assertNotIn(new_state, expected_terminal_states)
        self.assertEqual(env.obstacle_positions, layout)
        self.assertEqual(new_state.obstacles, layout)
        self.assertEqual(env.terminal_states(), expected_terminal_states)
        self.assertTrue(env._path_exists(layout))
        other_layout = other.obstacle_positions
        self.assertEqual(other.reset().obstacles, other_layout)
        self.assertEqual(other.obstacle_positions, other_layout)

    def test_hole_entry_terminates_episode(self):
        env = Environment(obstacles=True, render=False)
        layout = env.obstacle_positions
        movements = {
            Action.UP: (-1, 0),
            Action.DOWN: (1, 0),
            Action.LEFT: (0, -1),
            Action.RIGHT: (0, 1),
        }
        for hole in sorted(layout):
            for action, (row_delta, col_delta) in movements.items():
                start = (hole[0] - row_delta, hole[1] - col_delta)
                if (
                    0 <= start[0] < env.SIZE
                    and 0 <= start[1] < env.SIZE
                    and start not in layout
                    and start != (env.target.row, env.target.col)
                ):
                    env.state = State(*start, layout)
                    terminal = State(*hole, layout)
                    self.assertEqual(env.step(action), (terminal, -10.0))
                    self.assertTrue(env._terminated)
                    self.assertFalse(env._success)
                    self.assertIn(env.state, env.terminal_states())
                    with self.assertRaises(RuntimeError):
                        env.step(Action.UP)
                    env.reset()
                    self.assertFalse(env._terminated)
                    self.assertNotIn(env.state, env.terminal_states())
                    return
        self.fail("No non-terminal neighbor found for a hole")

    def test_invalid_action(self):
        env = Environment(render=False)
        with self.assertRaises(TypeError):
            env.step("UP")
        with self.assertRaises(ValueError):
            env.step(4)
        with self.assertRaises(TypeError):
            env.step(True)
        self.assertEqual(env.steps, 0)

    def test_debug_print(self):
        env = Environment(render=False)
        env.debug_print("""
            current state value: 1
            action selected: Up
        """)
        env.debug_print("reward: -1")
        self.assertEqual(
            env._debug_messages,
            ["reward: -1"],
        )
        env.reset()
        self.assertEqual(env._debug_messages, [])

    def test_step_automatically_updates_renderer(self):
        env = Environment(obstacles=False, render=False)
        renderer = Mock()
        env._renderer = renderer
        env.state = State(3, 0)

        self.assertEqual(env.step(Action.RIGHT), (State(3, 1), -1.0))
        renderer.before_step.assert_called_once_with(env)
        renderer.after_step.assert_called_once_with(env)

        env.reset()
        renderer.draw.assert_called_once_with(env)

    def test_debug_print_updates_renderer(self):
        env = Environment(render=False)
        renderer = Mock()
        env._renderer = renderer

        env.debug_print("new message")

        renderer._update_debug.assert_called_once_with("new message")

    def test_browser_control_state(self):
        import threading

        from src.find_the_dock.renderer import Renderer

        # Exercise browser command handling without opening a browser or server.
        renderer = Renderer.__new__(Renderer)
        renderer.fps = 30
        renderer._timed_fps = 30
        renderer.playing = True
        renderer._steps_requested = 0
        renderer._condition = threading.Condition()
        renderer._revision = 0
        renderer._latest_state = {
            "success": False,
            "finished": False,
            "fps": 30,
            "playing": True,
        }

        renderer._handle_control("toggle_play")
        self.assertFalse(renderer.playing)

        renderer._handle_control("step")
        self.assertEqual(renderer._steps_requested, 1)

        renderer._handle_control("fps_toggle")
        self.assertIsNone(renderer.fps)
        renderer._handle_control("fps_up")
        self.assertIsNone(renderer.fps)
        renderer._handle_control("fps_toggle")
        self.assertEqual(renderer.fps, 30)

        renderer._handle_control("fps_down")
        self.assertEqual(renderer.fps, 29)
        self.assertEqual(renderer._latest_state["fps"], 29)
        self.assertEqual(renderer._latest_state["playing"], False)

        # Reaching the dock ends an episode, not the training session.
        renderer._latest_state["success"] = True
        renderer._latest_state["finished"] = True
        renderer._steps_requested = 0
        renderer._handle_control("toggle_play")
        self.assertTrue(renderer.playing)
        renderer._handle_control("toggle_play")
        self.assertFalse(renderer.playing)
        renderer._handle_control("step")
        self.assertEqual(renderer._steps_requested, 0)

    def test_renderer_goal_state_is_published_and_held(self):
        import threading
        import time

        from src.find_the_dock.renderer import Renderer

        renderer = Renderer.__new__(Renderer)
        renderer.fps = 60
        renderer.playing = True
        renderer._manual_step = False
        renderer._closed = False
        renderer._condition = threading.Condition()
        renderer._latest_state = None
        renderer._revision = 0
        renderer._step_started = time.perf_counter()
        renderer.TERMINAL_HOLD_SECONDS = 0.05
        renderer._start_visible_until = 0.0

        env = Environment(obstacles=False, render=False)
        env.state = State(0, 3)
        env.steps = 1
        env._success = True
        env._terminated = True

        start = time.perf_counter()
        renderer.after_step(env)
        elapsed = time.perf_counter() - start

        self.assertEqual(renderer._latest_state["robot"], [0, 3])
        self.assertTrue(renderer._latest_state["success"])
        self.assertTrue(renderer._latest_state["finished"])
        self.assertGreaterEqual(elapsed, 0.045)

    def test_browser_step_advances_exactly_once_and_updates_display(self):
        import threading

        from src.find_the_dock.renderer import Renderer

        env = Environment(obstacles=False, render=False)
        env.state = State(3, 0)

        # Minimal renderer without starting an HTTP server.
        renderer = Renderer.__new__(Renderer)
        renderer.fps = 40
        renderer._timed_fps = 40
        renderer.playing = False
        renderer._steps_requested = 0
        renderer._manual_step = False
        renderer._closed = False
        renderer._condition = threading.Condition()
        renderer._latest_state = None
        renderer._revision = 0
        renderer._start_visible_until = 0.0
        renderer.START_HOLD_SECONDS = 0.0
        env._renderer = renderer

        renderer._handle_control("step")
        self.assertEqual(env.step(Action.RIGHT), (State(3, 1), -1.0))
        self.assertEqual(env.steps, 1)
        self.assertEqual(renderer._steps_requested, 0)
        self.assertEqual(renderer._latest_state["robot"], [3, 1])
        self.assertEqual(renderer._latest_state["steps"], 1)
        self.assertFalse(renderer.playing)

        # A second step must block until there is another button click.
        worker = threading.Thread(target=lambda: env.step(Action.RIGHT), daemon=True)
        worker.start()
        try:
            worker.join(timeout=0.05)
            self.assertTrue(worker.is_alive())
            self.assertEqual(env.steps, 1)

            renderer._handle_control("step")
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(env.steps, 2)
            self.assertEqual(renderer._latest_state["robot"], [3, 2])
            self.assertEqual(renderer._latest_state["steps"], 2)
        finally:
            with renderer._condition:
                renderer._closed = True
                renderer._condition.notify_all()
            worker.join(timeout=1)
            env._renderer = None

    def test_invalid_arguments(self):
        with self.assertRaises(ValueError):
            Environment(fps=0, render=False)
        with self.assertRaises(ValueError):
            Environment(fps=-1, render=False)
        with self.assertRaises(ValueError):
            Environment(fps=1.5, render=False)
        with self.assertRaises(ValueError):
            Environment(fps=True, render=False)
        env = Environment(fps=None, render=False)
        self.assertIsNone(env.fps)
        self.assertIsInstance(env.step(Action.UP)[1], float)
        with self.assertRaises(TypeError):
            Environment(obstacles=1, render=False)
        with self.assertRaises(TypeError):
            Environment(title=None, render=False)
        self.assertEqual(
            Environment(title="Custom title", render=False).title,
            "Custom title",
        )


if __name__ == "__main__":
    unittest.main()
