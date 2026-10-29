# Upwork portfolio item — copy/paste

**Project title**

```
Competitor Price Monitor — scraping, alerting and dashboard
```

**Description** (Upwork allows ~600 characters; this is ~580)

```
A price-tracking tool that scrapes competitor product pages on a schedule, stores full price history, and alerts on price drops and back-in-stock events via Slack webhook.

Built with Python, FastAPI, BeautifulSoup and SQLite. Handles the parts that usually break a scraper: exponential backoff, 429 rate-limit handling, both European and US money formats, and a hard failure when a selector stops matching — so you never get a "successful" run that silently scraped nothing.

The dashboard shows every product with an inline sparkline of its last 30 scrapes, what it costs now, and whether it is at its lowest price yet. CSV and JSON export, plus a /healthz endpoint for uptime monitoring. Adding a new shop is a config entry, not a code change. 15 passing tests.
```

**Skills to tag**

Python, Web Scraping, Data Scraping, Beautiful Soup, FastAPI, Automation, SQL

**Image to upload**

`screenshots/dashboard.jpg`

**Project URL**

Your GitHub repo link, once pushed.

---

## Talking points if a client asks about it on a call

- *"What happens when the site changes?"* — The run fails loudly and `/healthz`
  reports it. A scraper that writes zero rows and reports success is the real
  danger; this one can't.
- *"Can it do my site?"* — Yes, if the data is in the HTML. It's a selector
  config entry. If the site renders prices in JavaScript, I swap the fetch
  layer for Playwright, same structure.
- *"How do I get the data out?"* — CSV download, JSON API, or I push it
  straight into your Google Sheet.
- *"What does it cost to run?"* — It's a single Python process plus SQLite. A
  €5/month VPS handles thousands of products.
