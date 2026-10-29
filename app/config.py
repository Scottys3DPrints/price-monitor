"""Scrape targets and runtime settings.

A target is pure config: to monitor a different shop you add an entry here
rather than touching the scraper. That is the whole point of the structure --
most client work on this kind of job is "same scraper, different selectors".
"""

import os

DB_PATH = os.environ.get("PRICE_MONITOR_DB", "price_monitor.db")

# Seconds to wait between requests to the same host. Be a good citizen; this is
# also what keeps you off a rate limiter.
REQUEST_DELAY = float(os.environ.get("PRICE_MONITOR_DELAY", "1.0"))

REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
USER_AGENT = "price-monitor/1.0 (+contact: you@example.com)"

# Alert when a price drops by at least this fraction of the previous price.
ALERT_DROP_THRESHOLD = float(os.environ.get("PRICE_MONITOR_DROP", "0.05"))

# Optional: POST alerts here as JSON. Slack incoming webhooks work as-is.
ALERT_WEBHOOK_URL = os.environ.get("PRICE_MONITOR_WEBHOOK", "")

# How many price points each dashboard sparkline draws.
SPARKLINE_POINTS = 30


TARGETS = [
    {
        "key": "books-toscrape",
        # books.toscrape.com is a sandbox published for exactly this purpose.
        "label": "Books to Scrape (demo shop)",
        "listing_urls": [
            "https://books.toscrape.com/catalogue/category/books/mystery_3/index.html",
            "https://books.toscrape.com/catalogue/category/books/science-fiction_16/index.html",
        ],
        "selectors": {
            "item": "article.product_pod",
            "name": "h3 a",
            "name_attr": "title",
            "price": "p.price_color",
            "stock": "p.instock.availability",
            "link": "h3 a",
            "link_attr": "href",
        },
        "currency": "GBP",
    },
]


def target_by_key(key):
    for target in TARGETS:
        if target["key"] == key:
            return target
    return None
