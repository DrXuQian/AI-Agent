"""Fetch product prices from a target URL."""
import re
import urllib.request


def fetch_html(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read().decode("utf-8")


def parse_price(html: str) -> float | None:
    match = re.search(r'data-price="([\d.]+)"', html)
    if not match:
        return None
    return float(match.group(1))


def get_price(url: str) -> float | None:
    return parse_price(fetch_html(url))
