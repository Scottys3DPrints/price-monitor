#!/usr/bin/env python3
"""Run every configured target once, then deliver any alerts.

This is the entry point you put on a schedule:

    */30 * * * *  cd /srv/price-monitor && .venv/bin/python run_scrape.py

Exits non-zero when a target run fails, so cron or a systemd timer can notice.
"""

import logging
import sys

from app import alerts, config, db, scraper


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    log = logging.getLogger("run_scrape")

    db.init()

    failed_targets = []
    for target in config.TARGETS:
        log.info("scraping %s", target["label"])
        ok, failed, errors = scraper.scrape_target(target, on_change=alerts.detect)
        log.info("%s: %d rows, %d failures", target["key"], ok, failed)
        if errors:
            for error in errors:
                log.error("  %s", error)
        if ok == 0:
            failed_targets.append(target["key"])

    sent = alerts.deliver_pending()
    if sent:
        log.info("delivered %d alert(s)", sent)

    if failed_targets:
        log.error("no rows scraped for: %s", ", ".join(failed_targets))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
