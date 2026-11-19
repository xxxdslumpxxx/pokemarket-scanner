from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class CardIdentification(BaseModel):
    """Risultato dell'identificazione iniziale della carta tramite Vision AI."""
    model_config = ConfigDict(from_attributes=True)

    name: str
    set_name: Optional[str] = None
    card_number: Optional[str] = None
    total_in_set: Optional[str] = None
    language: Optional[str] = "Italiano"
    condition_estimate: Optional[str] = None
    is_holo: Optional[bool] = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw_notes: Optional[str] = None


class CardmarketPriceSummary(BaseModel):
    """Riepilogo dei prezzi aggregati da Cardmarket."""
    model_config = ConfigDict(from_attributes=True)

    currency: str = "EUR"
    lowest_price: Optional[float] = None
    average_price: Optional[float] = None
    highest_price: Optional[float] = None
    trend_price: Optional[float] = None
    avg1: Optional[float] = None
    avg7: Optional[float] = None
    avg30: Optional[float] = None
    reverse_holo_low: Optional[float] = None
    reverse_holo_trend: Optional[float] = None
    available_items: Optional[int] = None
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CardmarketListing(BaseModel):
    """Singolo annuncio di vendita su Cardmarket."""
    model_config = ConfigDict(from_attributes=True)

    seller: Optional[str] = None
    country: Optional[str] = None
    condition: Optional[str] = None
    language: Optional[str] = None
    is_foil: bool = False
    price: float


class CardInfoResponse(BaseModel):
    """Risposta completa inviata al frontend dopo l'elaborazione."""
    model_config = ConfigDict(from_attributes=True)

    identification: CardIdentification
    card_name: str
    set_name: Optional[str] = None
    set_code: Optional[str] = None
    card_number: Optional[str] = None
    rarity: Optional[str] = None
    supertype: Optional[str] = None
    subtypes: list[str] = Field(default_factory=list)
    hp: Optional[str] = None
    types: list[str] = Field(default_factory=list)
    artist: Optional[str] = None
    image_url: Optional[str] = None
    cardmarket_url: Optional[str] = None
    prices: CardmarketPriceSummary
    listings: list[CardmarketListing] = Field(default_factory=list)
    data_source: str = "Cardmarket"
    alternatives: list[dict] = Field(default_factory=list)
    tcgdex_id: Optional[str] = None
    set_symbol_url: Optional[str] = None
    match_info: Optional[str] = None
    timings: dict = Field(default_factory=dict)
