"""Price-drop and back-in-stock detection, plus optional webhook delivery."""

import logging

import requests

from app import config, db

log = logging.getLogger(__name__)


def detect(conn, product_id, item, previous):
    """Compare this scrape against the last one and record any alert."""
    old_minor = previous["price_minor"]
    new_minor = item["price_minor"]

    if old_minor > 0:
        drop = (old_minor - new_minor) / old_minor
        if drop >= config.ALERT_DROP_THRESHOLD:
            db.insert_alert(conn, product_id, "price_drop", old_minor, new_minor)
            log.info("price drop %.0f%% on product %s", drop * 100, product_id)

    was_out = not previous["in_stock"]
    if was_out and item["in_stock"]:
        db.insert_alert(conn, product_id, "back_in_stock", old_minor, new_minor)
        log.info("back in stock: product %s", product_id)


def money(minor, currency):
    symbol = {"GBP": "£", "EUR": "€", "USD": "$"}.get(currency, "")
    return f"{symbol}{minor / 100:.2f}"


def deliver_pending():
    """POST undelivered alerts to the configured webhook, then mark them sent.

    No webhook configured is not an error -- alerts still land in the database
    and show on the dashboard.
    """
    if not config.ALERT_WEBHOOK_URL:
        return 0

    sent = 0
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT a.*, p.name, p.url, p.currency
            FROM alerts a JOIN products p ON p.id = a.product_id
            WHERE a.delivered = 0 ORDER BY a.id
            """
        ).fetchall()

        for row in rows:
            if row["kind"] == "price_drop":
                text = (f"Price drop: {row['name']} "
                        f"{money(row['old_minor'], row['currency'])} -> "
                        f"{money(row['new_minor'], row['currency'])}\n{row['url']}")
            else:
                text = f"Back in stock: {row['name']}\n{row['url']}"

            try:
                response = requests.post(
                    config.ALERT_WEBHOOK_URL, json={"text": text}, timeout=10
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                # Leave it undelivered; the next run retries it.
                log.error("alert %s delivery failed: %s", row["id"], exc)
                continue

            conn.execute("UPDATE alerts SET delivered = 1 WHERE id = ?", (row["id"],))
            sent += 1

    return sent
