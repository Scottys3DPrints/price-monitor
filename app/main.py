"""Dashboard and JSON/CSV API.

    uvicorn app.main:app --reload
"""

import csv
import io
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app import config, db

TEMPLATES = Path(__file__).parent / "templates"

SPARK_WIDTH = 132
SPARK_HEIGHT = 30
SPARK_PAD = 3


@asynccontextmanager
async def lifespan(_app):
    db.init()
    yield


app = FastAPI(title="Price Monitor", lifespan=lifespan)
jinja = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html"]),
)


def money(minor, currency):
    if minor is None:
        return "--"
    symbol = {"GBP": "£", "EUR": "€", "USD": "$"}.get(currency, "")
    return f"{symbol}{minor / 100:,.2f}"


def sparkline(points):
    """Turn a price series into SVG polyline coordinates.

    Returns None for a series too short to say anything, so the template can
    show a dash instead of a misleading flat line.
    """
    if not points or len(points) < 2:
        return None

    low, high = min(points), max(points)
    span = high - low
    usable_height = SPARK_HEIGHT - (2 * SPARK_PAD)
    step = (SPARK_WIDTH - (2 * SPARK_PAD)) / (len(points) - 1)

    coordinates = []
    for index, value in enumerate(points):
        x = SPARK_PAD + (index * step)
        # A flat series sits on the centre line rather than at the top.
        ratio = 0.5 if span == 0 else (value - low) / span
        y = SPARK_PAD + usable_height - (ratio * usable_height)
        coordinates.append(f"{x:.1f},{y:.1f}")

    return " ".join(coordinates)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    with db.connect() as conn:
        products = db.products_with_latest(conn)
        series = db.recent_points(conn, config.SPARKLINE_POINTS)
        runs = db.recent_runs(conn)
        alerts = db.recent_alerts(conn)

    rows = []
    tracked_value = 0
    at_low_count = 0
    out_of_stock_count = 0

    for product in products:
        current = product["price_minor"]
        lowest = product["min_minor"]
        points = series.get(product["id"], [])

        at_low = current is not None and lowest is not None and current <= lowest
        if at_low:
            at_low_count += 1
        if not product["in_stock"]:
            out_of_stock_count += 1
        if current:
            tracked_value += current

        change = None
        if len(points) >= 2 and points[0]:
            change = (points[-1] - points[0]) / points[0] * 100

        rows.append({
            "id": product["id"],
            "name": product["name"],
            "url": product["url"],
            "price": money(current, product["currency"]),
            "low": money(lowest, product["currency"]),
            "high": money(product["max_minor"], product["currency"]),
            "samples": product["samples"],
            "in_stock": bool(product["in_stock"]),
            "at_low": at_low,
            "spark": sparkline(points),
            "change": change,
            "scraped_at": product["scraped_at"] or "never",
        })

    last_run = runs[0] if runs else None

    template = jinja.get_template("dashboard.html")
    return template.render(
        rows=rows,
        runs=runs,
        last_run=last_run,
        alerts=[{
            "name": alert["name"],
            "kind": alert["kind"],
            "kind_label": alert["kind"].replace("_", " "),
            "old": money(alert["old_minor"], alert["currency"]),
            "new": money(alert["new_minor"], alert["currency"]),
            "created_at": alert["created_at"],
            "delivered": bool(alert["delivered"]),
        } for alert in alerts],
        stats={
            "tracked": len(rows),
            "at_low": at_low_count,
            "out_of_stock": out_of_stock_count,
            "open_alerts": sum(1 for alert in alerts if not alert["delivered"]),
        },
        drop_threshold=int(config.ALERT_DROP_THRESHOLD * 100),
        spark_width=SPARK_WIDTH,
        spark_height=SPARK_HEIGHT,
    )


@app.get("/api/products")
def api_products():
    with db.connect() as conn:
        return [dict(row) for row in db.products_with_latest(conn)]


@app.get("/api/products/{product_id}/history")
def api_history(product_id: int):
    with db.connect() as conn:
        rows = db.price_history(conn, product_id)
        if not rows:
            raise HTTPException(404, "no price history for that product")
        return [dict(row) for row in rows]


@app.get("/export.csv")
def export_csv():
    """Flat export of every price point. This is the deliverable clients ask
    for on day two, so it ships on day one."""
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT p.name, p.url, p.currency, pr.price_minor, pr.in_stock,
                   pr.scraped_at
            FROM prices pr JOIN products p ON p.id = pr.product_id
            ORDER BY p.name, pr.scraped_at
            """
        ).fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["name", "url", "currency", "price", "in_stock", "scraped_at"])
    for row in rows:
        writer.writerow([
            row["name"], row["url"], row["currency"],
            f"{row['price_minor'] / 100:.2f}",
            "yes" if row["in_stock"] else "no",
            row["scraped_at"],
        ])

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="prices.csv"'},
    )


@app.get("/healthz")
def healthz():
    """Last run status, for uptime monitoring."""
    with db.connect() as conn:
        runs = db.recent_runs(conn, limit=1)

    if not runs:
        return {
            "status": "unknown",
            "detail": "no runs recorded yet",
            "finished_at": None,
            "rows_written": 0,
            "listings_failed": 0,
        }

    last = runs[0]
    return {
        "status": last["status"],
        "detail": last["error"],
        "finished_at": last["finished_at"],
        "rows_written": last["ok_count"],
        "listings_failed": last["fail_count"],
    }
