import unittest
from unittest.mock import Mock

from src.find_the_dock import Action, Environment, State


class EnvironmentTests(unittest.TestCase):
    def test_grid_and_actions(self):
        env = Environment(render=False)
        self.assertEqual(len(env.states()), 16)
        self.assertEqual(env.actions(), Action.all())
        previous_start = env.start
        state = env.reset()
        self.assertEqual((state.row, state.col), (env.start.row, env.start.col))
        self.assertNotEqual(env.start, previous_start)
        self.assertNotEqual((state.row, state.col), (env.target.row, env.target.col))
        self.assertEqual(
            {Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT}, set(env.actions())
        )
        self.assertEqual({State(0, 0): 1}[State(0, 0)], 1)
        self.assertEqual(env.terminal(), State(0, 3))

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
        env = Environment(render=False)
        env.state = State(3, 0)
        self.assertEqual(env.step(Action.RIGHT), (State(3, 1), -1.0))
        self.assertEqual(env.step(Action.DOWN), (State(3, 1), -5.0))
        self.assertEqual(env.step(Action.LEFT), (State(3, 0), -1.0))
        self.assertEqual(env.step(Action.LEFT), (State(3, 0), -5.0))
        self.assertNotEqual(env.state, env.terminal())

    def test_state_keeps_layout_across_actions(self):
        env = Environment(obstacles=True, seed=42, render=False)
        layout = env.obstacle_positions
        next_state, _ = env.step(Action.UP)
        self.assertEqual(next_state.obstacles, layout)
        self.assertEqual(env.state.obstacles, layout)

    def test_integer_action_compatibility(self):
        env = Environment(render=False)
        env.state = State(3, 0)
        self.assertEqual(env.step(3), (State(3, 1), -1.0))

    def test_goal_is_terminal(self):
        env = Environment(render=False)
        env.state = State(0, 2)
        self.assertEqual(env.step(Action.RIGHT), (State(0, 3), 100.0))
        self.assertEqual(env.state, env.terminal())
        self.assertTrue(env._success)
        self.assertFalse(env._truncated)
        with self.assertRaises(RuntimeError):
            env.step(Action.LEFT)
        previous_start = env.start
        state = env.reset()
        self.assertEqual((state.row, state.col), (env.start.row, env.start.col))
        self.assertNotEqual(env.start, previous_start)
        self.assertNotEqual((state.row, state.col), (env.target.row, env.target.col))
        self.assertNotEqual(env.state, env.terminal())

    def test_truncation(self):
        env = Environment(max_steps=2, render=False)
        env.step(Action.LEFT)
        env.step(Action.LEFT)
        self.assertTrue(env._truncated)
        self.assertFalse(env._success)
        self.assertNotEqual(env.state, env.terminal())
        with self.assertRaises(RuntimeError):
            env.step(Action.UP)

    def test_obstacles_stay_fixed_between_episodes_and_are_in_state(self):
        env = Environment(obstacles=True, seed=42, render=False)
        other = Environment(obstacles=True, seed=42, render=False)
        self.assertEqual(env.obstacle_positions, other.obstacle_positions)
        self.assertEqual(len(env.obstacle_positions), 2)
        self.assertEqual(len(env.states()), 14)
        self.assertNotIn((env.start.row, env.start.col), env.obstacle_positions)
        self.assertNotIn((env.target.row, env.target.col), env.obstacle_positions)
        self.assertNotEqual(env.start, env.target)
        self.assertTrue(env._path_exists(env.obstacle_positions))
        self.assertEqual(env.state.obstacles, env.obstacle_positions)
        self.assertEqual(env.terminal().obstacles, env.obstacle_positions)
        self.assertTrue(
            all(s.obstacles == env.obstacle_positions for s in env.states())
        )
        previous = env.obstacle_positions
        previous_start = env.start
        new_state = env.reset()
        self.assertNotEqual(env.start, previous_start)
        self.assertNotIn((new_state.row, new_state.col), env.obstacle_positions)
        self.assertEqual(env.obstacle_positions, previous)
        self.assertEqual(new_state.obstacles, env.obstacle_positions)
        self.assertTrue(env._path_exists(env.obstacle_positions))
        self.assertEqual(env.obstacle_positions, other.reset().obstacles)
        self.assertEqual(State(new_state.row, new_state.col, previous), new_state)

    def test_obstacle_collision(self):
        env = Environment(obstacles=True, seed=42, render=False)
        movements = {
            Action.UP: (-1, 0),
            Action.DOWN: (1, 0),
            Action.LEFT: (0, -1),
            Action.RIGHT: (0, 1),
        }
        for blocked in env.obstacle_positions:
            for action, (row_delta, col_delta) in movements.items():
                possible_start = State(
                    blocked[0] - row_delta,
                    blocked[1] - col_delta,
                    env.obstacle_positions,
                )
                if possible_start in env.states():
                    env.state = possible_start
                    self.assertEqual(env.step(action), (possible_start, -5.0))
                    return
        self.fail("No adjacent traversable cell found")

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
        env.print("""
            current state value: 1
            action selected: Up
        """)
        env.print("reward: -1")
        self.assertEqual(
            env._debug_messages,
            ["reward: -1"],
        )
        env.reset()
        self.assertEqual(env._debug_messages, [])

    def test_step_automatically_updates_renderer(self):
        env = Environment(render=False)
        renderer = Mock()
        env._renderer = renderer
        env.state = State(3, 0)

        self.assertEqual(env.step(Action.RIGHT), (State(3, 1), -1.0))
        renderer.before_step.assert_called_once_with(env)
        renderer.after_step.assert_called_once_with(env)

        env.reset()
        renderer.draw.assert_called_once_with(env)
        env.close()

    def test_close_renderer(self):
        env = Environment(render=False)
        renderer = Mock()
        env._renderer = renderer

        env.close()

        renderer.close.assert_called_once()
        self.assertIsNone(env._renderer)

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
            "truncated": False,
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

    def test_browser_step_advances_exactly_once_and_updates_display(self):
        import threading
        import time

        from src.find_the_dock.renderer import Renderer

        env = Environment(render=False)
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
        renderer._last_publish = time.perf_counter()
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
        with self.assertRaises(ValueError):
            Environment(max_steps=0, render=False)


if __name__ == "__main__":
    unittest.main()
