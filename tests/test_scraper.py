"""Parsing and failure behaviour -- the two things that actually break.

Run: pytest -q
"""

import pytest

from app.scraper import ScrapeError, parse_listing, parse_price_minor

SELECTORS = {
    "item": "article.product_pod",
    "name": "h3 a",
    "name_attr": "title",
    "price": "p.price_color",
    "stock": "p.instock.availability",
    "link": "h3 a",
    "link_attr": "href",
}

LISTING_HTML = """
<section>
  <article class="product_pod">
    <h3><a href="../book-one_1/index.html" title="Book One: A Study">Book One</a></h3>
    <p class="price_color">£51.77</p>
    <p class="instock availability">In stock</p>
  </article>
  <article class="product_pod">
    <h3><a href="../book-two_2/index.html" title="Book Two">Book Two</a></h3>
    <p class="price_color">£1,234.50</p>
    <p class="instock availability">Out of stock</p>
  </article>
</section>
"""


class TestPriceParsing:
    @pytest.mark.parametrize("text,expected", [
        ("£51.77", 5177),
        ("51.77", 5177),
        ("$1,234.56", 123456),          # comma groups, dot decimal
        ("1.234,56 €", 123456),         # dot groups, comma decimal
        ("1.234 €", 123400),            # dot groups, no decimal part
        ("1,234", 123400),              # comma groups, no decimal part
        ("€ 9", 900),
        ("12.5", 1250),                 # single decimal digit
        ("1 234,50 kr", 123450),        # space-grouped
    ])
    def test_parses_both_conventions(self, text, expected):
        assert parse_price_minor(text) == expected

    def test_raises_when_there_is_no_number(self):
        # A sold-out page often replaces the price with words. Better to fail
        # the row than to write a zero that looks like a free product.
        with pytest.raises(ScrapeError):
            parse_price_minor("Price on request")


class TestListingParsing:
    def test_extracts_every_field(self):
        items = parse_listing(LISTING_HTML, "https://shop.example/cat/", SELECTORS)
        assert len(items) == 2

        first = items[0]
        assert first["name"] == "Book One: A Study"
        assert first["price_minor"] == 5177
        assert first["in_stock"] is True
        assert first["url"] == "https://shop.example/book-one_1/index.html"

    def test_reads_stock_state_per_item(self):
        items = parse_listing(LISTING_HTML, "https://shop.example/cat/", SELECTORS)
        assert items[1]["in_stock"] is False
        assert items[1]["price_minor"] == 123450

    def test_resolves_relative_links_against_the_listing_url(self):
        items = parse_listing(LISTING_HTML, "https://shop.example/cat/", SELECTORS)
        assert all(item["url"].startswith("https://shop.example/") for item in items)

    def test_a_selector_that_matches_nothing_is_an_error(self):
        # The single most important behaviour here: when the shop changes its
        # markup we must fail, not write zero rows and report success.
        with pytest.raises(ScrapeError, match="matched 0 items"):
            parse_listing("<html><body>redesigned</body></html>",
                          "https://shop.example/cat/", SELECTORS)

    def test_items_missing_a_field_are_skipped_not_fatal(self):
        html = LISTING_HTML + """
          <article class="product_pod"><h3><a href="x">No price</a></h3></article>
        """
        items = parse_listing(html, "https://shop.example/cat/", SELECTORS)
        assert len(items) == 2
