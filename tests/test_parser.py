from backend.cardmarket_parser import (
    build_cardmarket_search_url,
    compute_price_summary_from_listings,
    extract_cardmarket_from_har,
    parse_eur_price,
)
from backend.models import CardmarketListing


def test_parse_eur_price():
    assert parse_eur_price("12,50 €") == 12.50
    assert parse_eur_price("1.234,56 €") == 1234.56
    assert parse_eur_price(9.9) == 9.9
    assert parse_eur_price(None) is None


def test_compute_price_summary_from_listings():
    listings = [
        CardmarketListing(seller="A", price=10.0),
        CardmarketListing(seller="B", price=20.0),
        CardmarketListing(seller="C", price=30.0),
    ]
    summary = compute_price_summary_from_listings(listings)
    assert summary.lowest_price == 10.0
    assert summary.average_price == 20.0
    assert summary.highest_price == 30.0
    assert summary.available_items == 3


def test_extract_cardmarket_from_har():
    har = {
        "log": {
            "entries": [
                {
                    "request": {"url": "https://www.cardmarket.com/img/logo.png", "method": "GET"},
                    "response": {"status": 200, "content": {"mimeType": "image/png"}},
                },
                {
                    "request": {
                        "url": "https://www.cardmarket.com/en/Pokemon/Products/Singles/151/Charizard-ex",
                        "method": "GET",
                    },
                    "response": {
                        "status": 200,
                        "content": {
                            "mimeType": "application/json",
                            "text": '{"product": "Charizard ex", "lowPrice": 120.0}',
                        },
                    },
                },
            ]
        }
    }
    res = extract_cardmarket_from_har(har)
    assert len(res["endpoints"]) == 1
    assert len(res["product_pages"]) == 1
    assert len(res["extracted_data"]) == 1


def test_build_cardmarket_search_url():
    url = build_cardmarket_search_url("Charizard ex", "199/165", "151")
    assert "cardmarket.com/en/Pokemon/Products/Search" in url
    assert "Charizard" in url
