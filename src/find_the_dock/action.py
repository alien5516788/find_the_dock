from enum import IntEnum


class Action(IntEnum):
    "Actions that can be taken by the agent."

    UP = 0
    DOWN = 1
    LEFT = 2
    RIGHT = 3

    @classmethod
    def all(cls) -> list["Action"]:
        return list(cls)
