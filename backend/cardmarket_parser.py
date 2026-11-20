from datetime import datetime, timezone
import json
import re
import urllib.parse
from typing import Any, Optional

from .models import CardmarketListing, CardmarketPriceSummary


def parse_eur_price(value: Any) -> Optional[float]:
    """
    Normalizza stringhe di prezzo in formato europeo (es. '1.234,56 €') in float.
    Gestisce anche int, float e None.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)

    try:
        clean_val = str(value).replace("€", "").replace("EUR", "").strip()
        clean_val = re.sub(r"[^\d.,]", "", clean_val)
        if not clean_val:
            return None
        if "," in clean_val and "." in clean_val:
            # Formato europeo 1.234,56
            if clean_val.rfind(",") > clean_val.rfind("."):
                clean_val = clean_val.replace(".", "").replace(",", ".")
            else:
                clean_val = clean_val.replace(",", "")
        elif "," in clean_val:
            clean_val = clean_val.replace(",", ".")
        return round(float(clean_val), 2)
    except (ValueError, TypeError):
        return None


def compute_price_summary_from_listings(
    listings: list[CardmarketListing],
    fallback_trend: Optional[float] = None,
    fallback_avg: Optional[float] = None,
    avg1: Optional[float] = None,
    avg7: Optional[float] = None,
    avg30: Optional[float] = None,
    reverse_holo_low: Optional[float] = None,
    reverse_holo_trend: Optional[float] = None,
    updated_at: Optional[str] = None,
) -> CardmarketPriceSummary:
    """
    Calcola statistiche di prezzo (più basso, medio, più alto) partendo da una lista di listing attivi.
    """
    ts = updated_at or datetime.now(timezone.utc).isoformat()
    prices = [l.price for l in listings if l.price and l.price > 0]

    if not prices:
        return CardmarketPriceSummary(
            average_price=fallback_avg,
            trend_price=fallback_trend,
            avg1=avg1,
            avg7=avg7,
            avg30=avg30,
            reverse_holo_low=reverse_holo_low,
            reverse_holo_trend=reverse_holo_trend,
            available_items=0,
            updated_at=ts,
        )

    avg_price = round(sum(prices) / len(prices), 2)
    return CardmarketPriceSummary(
        lowest_price=round(min(prices), 2),
        average_price=avg_price,
        highest_price=round(max(prices), 2),
        trend_price=fallback_trend or avg_price,
        avg1=avg1,
        avg7=avg7,
        avg30=avg30,
        reverse_holo_low=reverse_holo_low,
        reverse_holo_trend=reverse_holo_trend,
        available_items=len(prices),
        updated_at=ts,
    )


def extract_cardmarket_from_har(har_data: dict) -> dict:
    """
    Analizza un file HAR (catturato con reverse-api-engineer) per estrarre endpoint API
    e dati strutturati da cardmarket.com filtrando asset statici e tracker.
    """
    results: dict[str, Any] = {
        "endpoints": [],
        "extracted_data": [],
        "product_pages": [],
    }

    entries = har_data.get("log", {}).get("entries", [])
    if not entries:
        return results

    ignored_extensions = (
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
        ".css", ".js", ".woff", ".woff2", ".ttf", ".ico", ".map",
    )

    seen_urls: set[str] = set()
    for entry in entries:
        request = entry.get("request", {})
        response = entry.get("response", {})
        url = request.get("url", "")

        if "cardmarket.com" not in url.lower():
            continue

        path_lower = urllib.parse.urlparse(url).path.lower()
        if any(path_lower.endswith(ext) for ext in ignored_extensions):
            continue

        if url not in seen_urls:
            seen_urls.add(url)
            results["endpoints"].append(
                {
                    "url": url,
                    "method": request.get("method", "GET"),
                    "status": response.get("status", 0),
                    "mime_type": response.get("content", {}).get("mimeType", ""),
                }
            )

        if "/Pokemon/Products/Singles/" in url:
            results["product_pages"].append(url)

        content = response.get("content", {})
        mime_type = content.get("mimeType", "")
        text = content.get("text", "")

        if "application/json" in mime_type and text:
            try:
                payload = json.loads(text)
                payload_str = str(payload).lower()
                if any(k in payload_str for k in ("price", "product", "article", "trend", "low")):
                    results["extracted_data"].append({"url": url, "payload": payload})
            except (json.JSONDecodeError, TypeError):
                continue

    return results


CARDMARKET_LANGUAGE_IDS: dict[str, int] = {
    "english": 1, "en": 1, "inglese": 1,
    "french": 2, "français": 2, "fr": 2, "francese": 2,
    "german": 3, "deutsch": 3, "de": 3, "tedesco": 3,
    "spanish": 4, "español": 4, "es": 4, "spagnolo": 4,
    "italian": 5, "italiano": 5, "it": 5,
    "japanese": 7, "jp": 7, "giapponese": 7,
    "portuguese": 8, "português": 8, "pt": 8, "portoghese": 8,
}


def build_cardmarket_search_url(
    name: str,
    card_number: Optional[str] = None,
    set_name: Optional[str] = None,
    language: Optional[str] = None,
    min_condition: int = 2,
) -> str:
    """
    Costruisce l'URL di ricerca ufficiale su Cardmarket filtrato sulle carte singole Pokémon,
    pre-impostato sulla lingua rilevata e condizione minima Near Mint (minCondition=2).
    """
    base_url = "https://www.cardmarket.com/en/Pokemon/Products/Singles"
    num_only = card_number.split("/")[0].strip() if card_number else None
    parts = [p.strip() for p in (name, num_only) if p and p.strip()]
    params: dict[str, Any] = {
        "searchString": " ".join(parts),
        "minCondition": min_condition,
    }
    if language:
        lang_id = CARDMARKET_LANGUAGE_IDS.get(language.strip().lower())
        if lang_id:
            params["language"] = lang_id
    return f"{base_url}?{urllib.parse.urlencode(params)}"
