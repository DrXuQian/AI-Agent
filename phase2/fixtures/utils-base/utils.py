"""Utility functions for the demo project."""


def add(a: int, b: int) -> int:
    """Return the sum of two numbers."""
    return a + b


def multiply(a: int, b: int) -> int:
    """Return the product of two numbers."""
    return a * b


def fibonacci(n: int) -> list[int]:
    """Return the first n Fibonacci numbers."""
    if n <= 0:
        return []
    if n == 1:
        return [0]
    seq = [0, 1]
    for _ in range(2, n):
        seq.append(seq[-1] + seq[-2])
    return seq
