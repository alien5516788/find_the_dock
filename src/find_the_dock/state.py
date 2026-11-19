class State:
    """Robot position and the obstacle layout currently visible to the agent."""

    __slots__ = ("row", "col", "obstacles")

    def __init__(
        self, row: int, col: int, obstacles: frozenset[tuple[int, int]] = frozenset()
    ) -> None:
        object.__setattr__(self, "row", row)
        object.__setattr__(self, "col", col)
        object.__setattr__(self, "obstacles", frozenset(obstacles))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("State is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("State is immutable")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, State):
            return NotImplemented
        return (
            self.row == other.row
            and self.col == other.col
            and self.obstacles == other.obstacles
        )

    def __hash__(self) -> int:
        return hash((self.row, self.col, self.obstacles))

    def __repr__(self) -> str:
        return f"State(row={self.row}, col={self.col}, obstacles={self.obstacles})"
