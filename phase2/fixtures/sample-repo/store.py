"""Persist price observations to SQLite."""
import sqlite3
from datetime import datetime


def init_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            price REAL NOT NULL,
            observed_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def record(path: str, url: str, price: float) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO observations (url, price, observed_at) VALUES (?, ?, ?)",
        (url, price, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def latest(path: str, url: str) -> float | None:
    conn = sqlite3.connect(path)
    row = conn.execute(
        "SELECT price FROM observations WHERE url=? ORDER BY observed_at DESC LIMIT 1",
        (url,),
    ).fetchone()
    conn.close()
    return row[0] if row else None
