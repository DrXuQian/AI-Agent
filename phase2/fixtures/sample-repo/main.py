"""Entry point. Runs one check cycle for each URL in watchlist.txt."""
import sys

from alerts import format_message, should_alert
from scraper import get_price
from store import init_db, latest, record


def check_one(db_path: str, url: str, threshold_pct: float) -> str | None:
    current = get_price(url)
    if current is None:
        return None
    previous = latest(db_path, url)
    record(db_path, url, current)
    if previous is not None and should_alert(previous, current, threshold_pct):
        return format_message(url, previous, current)
    return None


def main(argv: list[str]) -> int:
    db_path = "pricewatch.db"
    init_db(db_path)
    with open("watchlist.txt") as f:
        urls = [line.strip() for line in f if line.strip()]
    for url in urls:
        msg = check_one(db_path, url, threshold_pct=10.0)
        if msg:
            print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
