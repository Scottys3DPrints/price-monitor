#!/usr/bin/env python3
"""Backfill synthetic price history so the dashboard has something to show.

This writes FAKE historical points for products already in the database, so a
fresh clone shows trends, lows and alerts instead of a single flat row. Run it
once after your first real scrape. It never touches live scraping.

    python run_scrape.py     # real data, one point per product
    python seed_demo.py      # fake history behind those points
"""

import random
import sys
from datetime import datetime, timedelta, timezone

from app import db

DAYS = 21
SEED = 20261029  # fixed, so the demo looks the same for everyone


def main():
    random.seed(SEED)
    db.init()

    with db.connect() as conn:
        products = conn.execute(
            "SELECT id, name FROM products ORDER BY id"
        ).fetchall()
        if not products:
            print("No products yet. Run: python run_scrape.py", file=sys.stderr)
            return 1

        existing = conn.execute("SELECT COUNT(*) AS n FROM prices").fetchone()["n"]
        if existing > len(products):
            print(f"{existing} price rows already present; not seeding again.")
            return 0

        written = 0
        alerted = 0

        for product in products:
            current = conn.execute(
                "SELECT price_minor FROM prices WHERE product_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (product["id"],),
            ).fetchone()
            if not current:
                continue

            base = current["price_minor"]
            # Walk backwards from today so the newest real point stays newest.
            price = base
            for day in range(DAYS, 0, -1):
                stamp = (datetime.now(timezone.utc) - timedelta(days=day)) \
                    .isoformat(timespec="seconds")
                # +/-4% random walk, kept inside a sane band around base.
                price = int(price * random.uniform(0.96, 1.04))
                price = max(int(base * 0.7), min(int(base * 1.3), price))
                in_stock = random.random() > 0.05
                conn.execute(
                    "INSERT INTO prices (product_id, price_minor, in_stock, "
                    "scraped_at) VALUES (?, ?, ?, ?)",
                    (product["id"], price, 1 if in_stock else 0, stamp),
                )
                written += 1

            # Give roughly a fifth of the catalogue a visible drop alert.
            if random.random() < 0.2:
                old = int(base * 1.25)
                db.insert_alert(conn, product["id"], "price_drop", old, base)
                alerted += 1

    print(f"Seeded {written} synthetic price points across {len(products)} "
          f"products, {alerted} demo alerts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
