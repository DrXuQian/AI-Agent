"""Tests for cart module. One test fails due to a planted bug."""
import unittest

from cart import apply_discount, apply_tax, subtotal, total


class TestSubtotal(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(subtotal([]), 0)

    def test_single_item(self):
        items = [{"price": 10.0, "quantity": 2}]
        self.assertEqual(subtotal(items), 20.0)

    def test_multiple_items(self):
        items = [
            {"price": 10.0, "quantity": 2},
            {"price": 5.5, "quantity": 4},
        ]
        self.assertEqual(subtotal(items), 42.0)


class TestApplyDiscount(unittest.TestCase):
    def test_10_percent(self):
        self.assertEqual(apply_discount(100.0, 10.0), 90.0)

    def test_zero(self):
        self.assertEqual(apply_discount(50.0, 0.0), 50.0)


class TestApplyTax(unittest.TestCase):
    def test_10_percent(self):
        """A 10% tax on $100 should be $110."""
        self.assertEqual(apply_tax(100.0, 10.0), 110.0)

    def test_zero_tax(self):
        self.assertEqual(apply_tax(50.0, 0.0), 50.0)


class TestTotal(unittest.TestCase):
    def test_no_discount_no_tax(self):
        items = [{"price": 10.0, "quantity": 1}]
        self.assertEqual(total(items), 10.0)

    def test_with_tax(self):
        items = [{"price": 100.0, "quantity": 1}]
        self.assertEqual(total(items, tax_pct=10.0), 110.0)


if __name__ == "__main__":
    unittest.main()
