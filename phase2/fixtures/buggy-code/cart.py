"""Shopping cart with discount and tax logic."""


def subtotal(items: list[dict]) -> float:
    """Sum item.price * item.quantity for all items."""
    return sum(item["price"] * item["quantity"] for item in items)


def apply_discount(amount: float, discount_pct: float) -> float:
    """Reduce amount by discount_pct percent."""
    return amount * (1 - discount_pct / 100)


def apply_tax(amount: float, tax_pct: float) -> float:
    """Add tax_pct percent tax to amount.

    BUG (planted): this multiplies by tax_pct/100 instead of adding it.
    """
    return amount * (tax_pct / 100)


def total(items: list[dict], discount_pct: float = 0.0, tax_pct: float = 0.0) -> float:
    """Compute final cart total: subtotal → discount → tax."""
    sub = subtotal(items)
    after_discount = apply_discount(sub, discount_pct)
    after_tax = apply_tax(after_discount, tax_pct)
    return round(after_tax, 2)
