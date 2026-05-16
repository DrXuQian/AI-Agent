"""Decide whether a price change warrants an alert."""


def should_alert(previous: float | None, current: float, threshold_pct: float = 10.0) -> bool:
    if previous is None or previous == 0:
        return False
    drop_pct = (previous - current) / previous * 100
    return drop_pct >= threshold_pct


def format_message(url: str, previous: float, current: float) -> str:
    drop = previous - current
    drop_pct = drop / previous * 100
    return (
        f"Price drop alert!\n"
        f"  URL:      {url}\n"
        f"  Was:      ${previous:.2f}\n"
        f"  Now:      ${current:.2f}\n"
        f"  Savings:  ${drop:.2f} ({drop_pct:.1f}% off)"
    )
