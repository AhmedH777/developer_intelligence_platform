"""A tiny calculator module used as a test fixture."""

PI = 3.14159


class Calculator:
    """Stateful calculator that accumulates a running total."""

    def __init__(self, start: int = 0) -> None:
        self.total = start

    def add(self, value: int) -> int:
        """Add ``value`` to the running total and return it."""
        self.total += value
        return self.total

    def reset(self) -> None:
        self.total = 0


def multiply(a: int, b: int) -> int:
    """Return the product of two integers."""
    return a * b


async def fetch_remote(url: str) -> str:
    return url
