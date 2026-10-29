"""Fetch listing pages and turn them into price rows.

Three things here are the difference between a scraper that survives a month
and one that dies silently on a Tuesday:

  * backoff and retry on transient failures and 429s
  * a per-request delay so we never look like a flood
  * a parse that raises when the selector stops matching, instead of writing
    zero rows and calling the run a success
"""

import logging
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app import config, db

log = logging.getLogger(__name__)

# A run of digits that may contain grouping marks or spaces inside it.
PRICE_RE = re.compile(r"\d[\d., \s]*\d|\d")


class ScrapeError(RuntimeError):
    pass


def parse_price_minor(text):
    """'£51.77' -> 5177, '1.234,56 €' -> 123456, '$1,234.56' -> 123456.

    Shops write money in both conventions and a naive float() silently turns
    "1,234.56" into 1.23. The decimal mark is whichever of '.' or ',' comes
    last AND is followed by one or two digits; anything else is grouping.
    """
    match = PRICE_RE.search(text)
    if not match:
        raise ScrapeError(f"no price found in {text!r}")

    raw = re.sub(r"[\s ]", "", match.group())

    decimal_sep = None
    for candidate in (".", ","):
        index = raw.rfind(candidate)
        if index == -1:
            continue
        if len(raw) - index - 1 in (1, 2):
            if decimal_sep is None or index > raw.rfind(decimal_sep):
                decimal_sep = candidate

    if decimal_sep is None:
        return int(re.sub(r"\D", "", raw)) * 100

    whole, _, fraction = raw.rpartition(decimal_sep)
    units = int(re.sub(r"\D", "", whole) or "0")
    cents = int((re.sub(r"\D", "", fraction) + "00")[:2])
    return units * 100 + cents


def fetch(url, session):
    """GET with retry and exponential backoff. Honours Retry-After on 429."""
    last_error = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=config.REQUEST_TIMEOUT)
            if response.status_code == 429:
                wait = float(response.headers.get("Retry-After", 2 ** attempt))
                log.warning("429 from %s, sleeping %.1fs", url, wait)
                time.sleep(wait)
                last_error = ScrapeError("rate limited")
                continue
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt == config.MAX_RETRIES:
                break
            wait = 2 ** attempt
            log.warning("attempt %d/%d failed for %s (%s), retrying in %ds",
                        attempt, config.MAX_RETRIES, url, exc, wait)
            time.sleep(wait)
    raise ScrapeError(f"giving up on {url}: {last_error}")


def parse_listing(html, base_url, selectors):
    """Return [{external_id, name, url, price_minor, in_stock}, ...]."""
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select(selectors["item"])
    if not nodes:
        # The page loaded but nothing matched. That is a broken selector, not
        # an empty shop -- fail loudly so the run is marked failed.
        raise ScrapeError(f"selector {selectors['item']!r} matched 0 items")

    items = []
    for node in nodes:
        name_node = node.select_one(selectors["name"])
        price_node = node.select_one(selectors["price"])
        link_node = node.select_one(selectors["link"])
        if not (name_node and price_node and link_node):
            log.warning("skipping item with missing fields")
            continue

        name = name_node.get(selectors.get("name_attr") or "", "").strip()
        if not name:
            name = name_node.get_text(strip=True)

        href = link_node.get(selectors.get("link_attr", "href"), "")
        url = urljoin(base_url, href)

        in_stock = True
        if selectors.get("stock"):
            stock_node = node.select_one(selectors["stock"])
            in_stock = bool(stock_node) and "in stock" in stock_node.get_text().lower()

        items.append({
            "external_id": url,
            "name": name,
            "url": url,
            "price_minor": parse_price_minor(price_node.get_text(strip=True)),
            "in_stock": in_stock,
        })
    return items


def scrape_target(target, on_change=None):
    """Scrape one configured target.

    Returns (rows_written, listings_failed, errors). A run is 'ok' only when
    every listing page parsed; one bad page out of two means half the
    catalogue is missing, and reporting that as success is how a monitor
    quietly stops being worth anything.
    """
    session = requests.Session()
    session.headers["User-Agent"] = config.USER_AGENT

    rows_written = 0
    listings_ok = 0
    listings_failed = 0
    errors = []

    with db.connect() as conn:
        run_id = db.start_run(conn, target["key"])

        for listing_url in target["listing_urls"]:
            try:
                html = fetch(listing_url, session)
                items = parse_listing(html, listing_url, target["selectors"])
            except ScrapeError as exc:
                listings_failed += 1
                errors.append(str(exc))
                log.error("listing failed: %s", exc)
                continue

            listings_ok += 1
            for item in items:
                product_id = db.upsert_product(
                    conn, target["key"], item["external_id"],
                    item["name"], item["url"], target["currency"],
                )
                previous = db.latest_price(conn, product_id)
                db.insert_price(conn, product_id, item["price_minor"], item["in_stock"])
                rows_written += 1

                if previous and on_change:
                    on_change(conn, product_id, item, previous)

            time.sleep(config.REQUEST_DELAY)

        if listings_failed == 0:
            status = "ok"
        elif listings_ok == 0:
            status = "failed"
        else:
            status = "partial"

        db.finish_run(conn, run_id, rows_written, listings_failed, status,
                      "; ".join(errors) or None)

    return rows_written, listings_failed, errors
