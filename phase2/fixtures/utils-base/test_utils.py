"""Tests for utility functions."""
import unittest
from utils import add, multiply, fibonacci


class TestAdd(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(add(2, 3), 5)

    def test_negative(self):
        self.assertEqual(add(-1, -2), -3)

    def test_zero(self):
        self.assertEqual(add(0, 0), 0)


class TestMultiply(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(multiply(3, 4), 12)

    def test_zero(self):
        self.assertEqual(multiply(5, 0), 0)


class TestFibonacci(unittest.TestCase):
    def test_five(self):
        self.assertEqual(fibonacci(5), [0, 1, 1, 2, 3])

    def test_one(self):
        self.assertEqual(fibonacci(1), [0])

    def test_zero(self):
        self.assertEqual(fibonacci(0), [])


if __name__ == "__main__":
    unittest.main()
