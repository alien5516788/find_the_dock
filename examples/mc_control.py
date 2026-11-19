import random

from src.find_the_dock import Action, Environment, State

qvalue: dict[tuple[State, Action], float] = {}


GAMMA: float = 0.9
ALPHA: float = 0.1


class Step:
    def __init__(self, s: State, a: Action, r: float):
        self.state = s
        self.action = a
        self.reward = r


def mc_control(episode: list[Step]):
    # We start as t+1 = terminal step which is not included in the episode
    #   and t = last step in the episode

    # G_t+1
    g = 0.0

    episode.reverse()
    for step in episode:
        # G_t = R_t+1 + γG_t+1
        g = step.reward + GAMMA * g

        # error = G_t - Q(S_t, A_t)
        error = g - qvalue.get((step.state, step.action), 0)

        # Q(S_t, A_t) <- Q(S_t) + α error
        qvalue[(step.state, step.action)] = (
            qvalue.get((step.state, step.action), 0) + ALPHA * error
        )


def action(s: State) -> Action:
    #  An action must be selected from a probability distribution
    #    based on π(a | s) for each action

    # Exploration
    EPSILON = 0.1

    if random.random() < EPSILON:
        return random.choice(Action.all())

    # Exploitation
    return max(Action.all(), key=lambda a: qvalue.get((s, a), 0.0))


def main():
    environment = Environment(fps=40, obstacles=True)
    episodes = 3000
    max_steps = 100

    for ep_no in range(episodes):
        s = environment.reset()

        # Generate one complete episode
        episode: list[Step] = []

        while s != environment.terminal() and len(episode) < max_steps:
            a = action(s)

            environment.print(
                f"Episode: {ep_no}\nState: {s}\nAction: {a.name}\nQ(s, a): {qvalue.get((s, a), 0)}"
            )

            # E(s, a) -> (s', r)
            (s_next, r) = environment.step(a)

            # Add step
            episode.append(Step(s, a, r))

            s = s_next

        mc_control(episode)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(e)
