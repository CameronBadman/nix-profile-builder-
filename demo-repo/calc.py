"""Tiny calculator module for the ACME profiles demo."""


def add(a: float, b: float) -> float:
    """Return the sum of a and b."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return a minus b."""
    return a - b


def divide(a: float, b: float) -> float:
    return a / b


def average(values: list[float]) -> float:
    """Return the arithmetic mean of values."""
    return sum(values) / len(values)
