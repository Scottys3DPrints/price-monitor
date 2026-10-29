"""SQLite storage.

Prices are stored as integer minor units (pence/cents). Floats drift, and a
client comparing a dashboard number against their own spreadsheet will notice.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY,
    target_key  TEXT NOT NULL,
    external_id TEXT NOT NULL,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    currency    TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    UNIQUE (target_key, external_id)
);

CREATE TABLE IF NOT EXISTS prices (
    id          INTEGER PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    price_minor INTEGER NOT NULL,
    in_stock    INTEGER NOT NULL,
    scraped_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prices_product ON prices(product_id, scraped_at);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    target_key  TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    ok_count    INTEGER NOT NULL DEFAULT 0,
    fail_count  INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'running',
    error       TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    kind        TEXT NOT NULL,
    old_minor   INTEGER,
    new_minor   INTEGER,
    created_at  TEXT NOT NULL,
    delivered   INTEGER NOT NULL DEFAULT 0
);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)


def start_run(conn, target_key):
    cur = conn.execute(
        "INSERT INTO runs (target_key, started_at) VALUES (?, ?)",
        (target_key, now()),
    )
    return cur.lastrowid


def finish_run(conn, run_id, ok_count, fail_count, status, error=None):
    conn.execute(
        "UPDATE runs SET finished_at = ?, ok_count = ?, fail_count = ?, "
        "status = ?, error = ? WHERE id = ?",
        (now(), ok_count, fail_count, status, error, run_id),
    )


def upsert_product(conn, target_key, external_id, name, url, currency):
    stamp = now()
    conn.execute(
        """
        INSERT INTO products (target_key, external_id, name, url, currency,
                              first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (target_key, external_id) DO UPDATE SET
            name = excluded.name,
            url = excluded.url,
            last_seen = excluded.last_seen
        """,
        (target_key, external_id, name, url, currency, stamp, stamp),
    )
    row = conn.execute(
        "SELECT id FROM products WHERE target_key = ? AND external_id = ?",
        (target_key, external_id),
    ).fetchone()
    return row["id"]


def latest_price(conn, product_id):
    return conn.execute(
        "SELECT price_minor, in_stock FROM prices WHERE product_id = ? "
        "ORDER BY scraped_at DESC, id DESC LIMIT 1",
        (product_id,),
    ).fetchone()


def insert_price(conn, product_id, price_minor, in_stock):
    conn.execute(
        "INSERT INTO prices (product_id, price_minor, in_stock, scraped_at) "
        "VALUES (?, ?, ?, ?)",
        (product_id, price_minor, 1 if in_stock else 0, now()),
    )


def insert_alert(conn, product_id, kind, old_minor, new_minor):
    conn.execute(
        "INSERT INTO alerts (product_id, kind, old_minor, new_minor, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (product_id, kind, old_minor, new_minor, now()),
    )


def products_with_latest(conn):
    return conn.execute(
        """
        SELECT p.id, p.name, p.url, p.currency, p.last_seen,
               pr.price_minor, pr.in_stock, pr.scraped_at,
               (SELECT MIN(price_minor) FROM prices WHERE product_id = p.id) AS min_minor,
               (SELECT MAX(price_minor) FROM prices WHERE product_id = p.id) AS max_minor,
               (SELECT COUNT(*) FROM prices WHERE product_id = p.id) AS samples
        FROM products p
        LEFT JOIN prices pr ON pr.id = (
            SELECT id FROM prices WHERE product_id = p.id
            ORDER BY scraped_at DESC, id DESC LIMIT 1
        )
        ORDER BY p.name
        """
    ).fetchall()


def price_history(conn, product_id, limit=200):
    return conn.execute(
        "SELECT price_minor, in_stock, scraped_at FROM prices "
        "WHERE product_id = ? ORDER BY scraped_at DESC, id DESC LIMIT ?",
        (product_id, limit),
    ).fetchall()


def recent_points(conn, per_product=30):
    """The last N price points for every product, oldest first.

    One query for the whole dashboard instead of one per row -- with a few
    hundred products the N+1 version is the difference between 40ms and four
    seconds.
    """
    rows = conn.execute(
        """
        SELECT product_id, price_minor, scraped_at FROM (
            SELECT product_id, price_minor, scraped_at, id,
                   ROW_NUMBER() OVER (
                       PARTITION BY product_id ORDER BY scraped_at DESC, id DESC
                   ) AS rn
            FROM prices
        )
        WHERE rn <= ?
        ORDER BY product_id, scraped_at, id
        """,
        (per_product,),
    ).fetchall()

    grouped = {}
    for row in rows:
        grouped.setdefault(row["product_id"], []).append(row["price_minor"])
    return grouped


def recent_runs(conn, limit=10):
    return conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def recent_alerts(conn, limit=25):
    return conn.execute(
        """
        SELECT a.*, p.name, p.currency
        FROM alerts a JOIN products p ON p.id = a.product_id
        ORDER BY a.id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
