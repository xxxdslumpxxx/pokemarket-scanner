import asyncio
import importlib.util
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from . import image_match
from .cardmarket_parser import (
    build_cardmarket_search_url,
    compute_price_summary_from_listings,
    extract_cardmarket_from_har,
    parse_eur_price,
)
from .models import (
    CardIdentification,
    CardInfoResponse,
    CardmarketListing,
    CardmarketPriceSummary,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
GENERATED_CLIENT_DIR = ROOT_DIR / "generated_client"
CAPTURES_DIR = ROOT_DIR / "captures"
DATA_DIR = ROOT_DIR / "data"
SETS_CACHE_FILE = DATA_DIR / "sets_cache.json"
TCGDEX = "https://api.tcgdex.net/v2"
HEADERS = {"User-Agent": "PokeMarketScanner/2.0", "Accept": "application/json"}

# Codice stampato in basso a sinistra -> id set TCGdex
SET_CODE_TO_TCGDEX = {
    "SSH": "swsh1", "RCL": "swsh2", "DAA": "swsh3", "CPA": "swsh3.5", "VIV": "swsh4", "SHF": "swsh4.5",
    "BST": "swsh5", "CRE": "swsh6", "EVS": "swsh7", "FST": "swsh8", "CEL": "cel25", "BRS": "swsh9",
    "ASR": "swsh10", "PGO": "swsh10.5", "LOR": "swsh11", "SIT": "swsh12", "CRZ": "swsh12.5",
    "SVI": "sv01", "PAL": "sv02", "OBF": "sv03", "MEW": "sv03.5", "PAR": "sv04", "PAF": "sv04.5",
    "TEF": "sv05", "TWM": "sv06", "SFA": "sv06.5", "SCR": "sv07", "SSP": "sv08", "PRE": "sv08.5",
    "JTG": "sv09", "DRI": "sv10", "SVP": "svp", "SWSH": "swshp",
}


def _norm_num(val: Optional[str]) -> str:
    if not val:
        return ""
    part = str(val).split("/")[0].strip().upper()
    m = re.match(r"^([A-Z]*)(\d+)$", part)
    if m:
        return f"{m.group(1)}{int(m.group(2))}"
    return part


def _norm_name(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


class CardmarketService:
    def __init__(self) -> None:
        self._reverse_client_module = self._load_generated_reverse_client()
        self._sets: dict[str, dict] = {}
        self._sets_loaded_at = 0.0
        self._detail_cache: dict[str, dict] = {}
        self._brief_cache: dict[str, list[dict]] = {}
        self._img_cache: dict[str, bytes] = {}
        self._http: Optional[httpx.AsyncClient] = None

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(6.0, connect=3.0),
                headers=HEADERS,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=30, max_keepalive_connections=15),
            )
        return self._http

    # ------------------------------------------------------------------ reverse-api-engineer
    def _load_generated_reverse_client(self) -> Optional[Any]:
        client_file = GENERATED_CLIENT_DIR / "cardmarket_client.py"
        if not client_file.exists():
            return None
        try:
            spec = importlib.util.spec_from_file_location("cardmarket_generated_client", client_file)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
        except Exception:
            return None
        return None

    @property
    def reverse_api_connected(self) -> bool:
        return self._reverse_client_module is not None

    def get_imported_har_summary(self) -> list[dict[str, Any]]:
        if not CAPTURES_DIR.exists():
            return []
        out = []
        for har_path in sorted(CAPTURES_DIR.glob("*.har")):
            try:
                parsed = extract_cardmarket_from_har(json.loads(har_path.read_text(encoding="utf-8")))
                out.append({"file": har_path.name, "endpoints_count": len(parsed["endpoints"])})
            except Exception:
                continue
        return out

    def _reverse_listings(self, ident: CardIdentification) -> tuple[list[CardmarketListing], dict]:
        mod = self._reverse_client_module
        if not mod or not hasattr(mod, "search_card"):
            return [], {}
        try:
            raw = mod.search_card(name=ident.name, card_number=ident.card_number, set_name=ident.set_name)
        except Exception:
            return [], {}
        if not isinstance(raw, dict):
            return [], {}
        listings = []
        for item in raw.get("listings", []):
            price = parse_eur_price(item.get("price"))
            if price:
                listings.append(
                    CardmarketListing(
                        seller=item.get("seller"), country=item.get("country"),
                        condition=item.get("condition"), language=item.get("language"),
                        is_foil=bool(item.get("is_foil", False)), price=price,
                    )
                )
        return listings, raw

    # ------------------------------------------------------------------ set cache
    async def _ensure_sets(self, client: httpx.AsyncClient) -> None:
        if self._sets and time.time() - self._sets_loaded_at < 86400:
            return
        try:
            if SETS_CACHE_FILE.exists() and time.time() - SETS_CACHE_FILE.stat().st_mtime < 86400:
                data = json.loads(SETS_CACHE_FILE.read_text(encoding="utf-8"))
                self._sets = {s["id"]: s for s in data}
                self._sets_loaded_at = time.time()
                return
        except Exception:
            pass
        try:
            resp = await client.get(f"{TCGDEX}/en/sets")
            if resp.status_code == 200:
                data = resp.json()
                self._sets = {s["id"]: s for s in data if s.get("id")}
                self._sets_loaded_at = time.time()
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                SETS_CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    def _set_of(self, card_id: str) -> tuple[str, dict]:
        set_id = card_id.rsplit("-", 1)[0] if "-" in card_id else card_id
        return set_id, self._sets.get(set_id, {})

    def _set_official(self, set_id: str) -> Optional[int]:
        cc = (self._sets.get(set_id) or {}).get("cardCount") or {}
        return cc.get("official") or cc.get("total")

    # ------------------------------------------------------------------ name variants
    def _build_name_variants(self, name: str) -> list[str]:
        raw = re.sub(r"\s+", " ", name.replace('"', "").strip())
        if not raw:
            return []
        spaced = re.sub(r"\s*&\s*", " & ", raw)
        spaced = re.sub(r"([A-Za-zÀ-ÿ]{3,}?)di\s*(Hisui|Galar|Alola|Paldea)", r"\1 di \2", spaced, flags=re.IGNORECASE)
        spaced = re.sub(r"([a-zà-ÿ])([A-Z])", r"\1 \2", spaced)
        spaced = re.sub(r"([a-zà-ÿ]{3,})(ex|gx|vmax|vstar)\b", r"\1 \2", spaced, flags=re.IGNORECASE)
        spaced = re.sub(r"\s+", " ", spaced).strip()

        variants: list[str] = []
        for pat, repl in (
            (r"^(.*?)\s+di\s+Hisui(.*)$", r"Hisuian \1\2"),
            (r"^(.*?)\s+di\s+Galar(.*)$", r"Galarian \1\2"),
            (r"^(.*?)\s+di\s+Alola(.*)$", r"Alolan \1\2"),
            (r"^(.*?)\s+di\s+Paldea(.*)$", r"Paldean \1\2"),
            (r"^(.*?)\s+Lucente(.*)$", r"Radiant \1\2"),
        ):
            if re.match(pat, spaced, flags=re.IGNORECASE):
                en = re.sub(r"\s+", " ", re.sub(pat, repl, spaced, flags=re.IGNORECASE)).strip()
                variants.append(en)
        for c in (spaced, raw):
            if c and c not in variants:
                variants.append(c)
        first = spaced.split()[0]
        if len(first) >= 3 and first not in variants:
            variants.append(first)
        # Gestisce OCR che taglia 'ex' in 'e' (es. 'Charizarde' -> 'Charizard')
        if len(first) >= 6 and first.lower().endswith("e"):
            trimmed = first[:-1]
            if trimmed not in variants:
                variants.append(trimmed)
        return variants

    async def _fast_lookup_by_number_and_total(
        self, client: httpx.AsyncClient, ident: CardIdentification
    ) -> list[dict]:
        """
        Ricerca ULTRA-VELOCE usando codice set o totale del set (es. 199/165 -> sv03.5-199).
        Funziona anche per set con solo SIMBOLO e anche se l'OCR ha storpiato il nome!
        """
        if not ident.card_number:
            return []

        candidate_set_ids: list[str] = []
        if ident.set_name:
            sid = SET_CODE_TO_TCGDEX.get(ident.set_name.upper().strip())
            if sid:
                candidate_set_ids.append(sid)

        if ident.total_in_set:
            tot_digits = re.sub(r"\D", "", ident.total_in_set)
            if tot_digits:
                tot_int = int(tot_digits)
                for sid, sinfo in self._sets.items():
                    cc = sinfo.get("cardCount") or {}
                    if cc.get("official") == tot_int or cc.get("total") == tot_int:
                        if sid not in candidate_set_ids:
                            candidate_set_ids.append(sid)

        if not candidate_set_ids or len(candidate_set_ids) > 12:
            return []

        num_raw = ident.card_number.strip().upper()
        num_int_str = str(int(num_raw)) if num_raw.isdigit() else num_raw
        num_padded = f"{int(num_raw):03d}" if num_raw.isdigit() else num_raw
        num_forms = list(dict.fromkeys([num_raw, num_padded, num_int_str]))

        async def _try_set(sid: str) -> Optional[dict]:
            # Prova tutte le forme del numero IN PARALLELO su EN (non sequenzialmente EN+IT!)
            reqs = [self._fetch_detail(client, f"{sid}-{nf}", en_only=True) for nf in num_forms]
            res = await asyncio.gather(*reqs, return_exceptions=True)
            for r in res:
                if isinstance(r, dict) and r.get("id"):
                    return r
            return None

        results = await asyncio.gather(*[_try_set(sid) for sid in candidate_set_ids], return_exceptions=True)
        found = [r for r in results if isinstance(r, dict) and r.get("id")]
        if not found:
            return []

        # Filtra per somiglianza minima con il nome letto (evita falsi positivi se il numero era letto male)
        variants_norm = [_norm_name(v) for v in self._build_name_variants(ident.name)]
        matched = []
        for det in found:
            dname = _norm_name(det.get("name"))
            if any(v and (v in dname or dname in v or (len(v) >= 4 and v[:4] == dname[:4])) for v in variants_norm):
                matched.append(det)
        return matched or found

    # ------------------------------------------------------------------ TCGdex
    async def _search_briefs(self, client: httpx.AsyncClient, name: str) -> list[dict]:
        for v in self._build_name_variants(name):
            key = v.lower()
            if key in self._brief_cache:
                if self._brief_cache[key]:
                    return self._brief_cache[key]
                continue
            res = await asyncio.gather(
                client.get(f"{TCGDEX}/en/cards", params={"name": v}),
                client.get(f"{TCGDEX}/it/cards", params={"name": v}),
                return_exceptions=True,
            )
            briefs: dict[str, dict] = {}
            for lang, r in zip(("en", "it"), res):
                if isinstance(r, Exception) or r.status_code != 200:
                    continue
                data = r.json()
                if isinstance(data, list):
                    for b in data:
                        if b.get("id") and b["id"] not in briefs:
                            b["_lang"] = lang
                            briefs[b["id"]] = b
            found = list(briefs.values())
            self._brief_cache[key] = found
            if found:
                return found
        return []

    async def _fetch_detail(self, client: httpx.AsyncClient, card_id: str, en_only: bool = False) -> Optional[dict]:
        if card_id in self._detail_cache:
            return self._detail_cache[card_id]
        langs = ("en",) if en_only else ("en", "it")
        for lang in langs:
            try:
                r = await client.get(f"{TCGDEX}/{lang}/cards/{card_id}")
                if r.status_code == 200:
                    det = r.json()
                    self._detail_cache[card_id] = det
                    return det
                if r.status_code == 404 and lang == "en" and not en_only:
                    continue
            except Exception:
                continue
        return None

    async def _visual_score(self, client: httpx.AsyncClient, brief: dict, user_card) -> float:
        img = brief.get("image")
        if not img or user_card is None:
            return 0.0
        url = f"{img}/low.png"
        try:
            data = self._img_cache.get(url)
            if data is None:
                r = await client.get(url)
                if r.status_code != 200:
                    return 0.0
                data = r.content
                self._img_cache[url] = data
            return await asyncio.to_thread(image_match.similarity, user_card, data)
        except Exception:
            return 0.0

    def _score(self, b: dict, ident: CardIdentification, variants_norm: set[str]) -> tuple[float, list[str]]:
        set_id, _ = self._set_of(b["id"])
        score, why = 0.0, []
        tnum = _norm_num(ident.card_number)
        if tnum:
            if _norm_num(b.get("localId")) == tnum:
                score += 100
                why.append(f"numero {ident.card_number}")
            else:
                score -= 40
        if ident.total_in_set:
            official = self._set_official(set_id)
            cc = (self._sets.get(set_id) or {}).get("cardCount") or {}
            totals = {str(x) for x in (cc.get("official"), cc.get("total")) if x}
            if official and str(int(re.sub(r"\D", "", ident.total_in_set) or 0)) in totals:
                score += 50
                why.append(f"totale /{ident.total_in_set}")
            elif official:
                score -= 15
        if ident.set_name:
            sid = SET_CODE_TO_TCGDEX.get(ident.set_name.upper().strip())
            if sid and sid == set_id:
                score += 80
                why.append(f"codice {ident.set_name}")
            elif sid:
                score -= 30
        if _norm_name(b.get("name")) in variants_norm:
            score += 5
        if b.get("image"):
            score += 1
        return score, why

    def _alt_entry(self, b: dict) -> dict:
        set_id, sinfo = self._set_of(b["id"])
        official = self._set_official(set_id)
        lid = b.get("localId")
        return {
            "tcgdex_id": b["id"],
            "name": b.get("name"),
            "set_name": sinfo.get("name") or set_id,
            "card_number": f"{lid}/{official}" if lid and official else lid,
            "image_url": f"{b['image']}/low.webp" if b.get("image") else None,
        }

    def _merge_prices(self, cm: dict[str, Any], listings: list[CardmarketListing]) -> CardmarketPriceSummary:
        low = parse_eur_price(cm.get("low") or cm.get("lowPrice"))
        avg = parse_eur_price(cm.get("avg") or cm.get("averageSellPrice"))
        trend = parse_eur_price(cm.get("trend") or cm.get("trendPrice"))
        avg1 = parse_eur_price(cm.get("avg1"))
        avg7 = parse_eur_price(cm.get("avg7"))
        avg30 = parse_eur_price(cm.get("avg30"))
        rev_low = parse_eur_price(cm.get("low-holo") or cm.get("reverseHoloLow"))
        rev_trend = parse_eur_price(cm.get("trend-holo") or cm.get("reverseHoloTrend"))
        updated = cm.get("updated") or cm.get("updatedAt")
        if listings:
            return compute_price_summary_from_listings(
                listings, fallback_trend=trend, fallback_avg=avg, avg1=avg1, avg7=avg7, avg30=avg30,
                reverse_holo_low=rev_low, reverse_holo_trend=rev_trend, updated_at=updated,
            )
        normal = [p for p in (low, trend, avg1, avg7, avg30, avg) if p is not None and p > 0]
        # Su Cardmarket il valore medio principale di riferimento è il Price Trend (poi 7g / 30g)
        primary_avg = trend or avg7 or avg30 or avg
        return CardmarketPriceSummary(
            lowest_price=low if low else (min(normal) if normal else None),
            average_price=primary_avg,
            highest_price=max(normal) if normal else None,
            trend_price=trend, avg1=avg1, avg7=avg7, avg30=avg30,
            reverse_holo_low=rev_low, reverse_holo_trend=rev_trend,
            updated_at=str(updated) if updated else CardmarketPriceSummary().updated_at,
        )

    def _build_response(
        self, ident: CardIdentification, det: dict, alternatives: list[dict], match_info: Optional[str],
        listings: list[CardmarketListing], reverse_raw: dict,
    ) -> CardInfoResponse:
        set_obj = det.get("set") or {}
        sid = set_obj.get("id") or self._set_of(det.get("id", ""))[0]
        sinfo = self._sets.get(sid, {})
        cc = set_obj.get("cardCount") or sinfo.get("cardCount") or {}
        official = cc.get("official") or cc.get("total")
        lid = det.get("localId")
        cm = (det.get("pricing") or {}).get("cardmarket") or {}
        img = det.get("image")
        symbol = set_obj.get("symbol") or sinfo.get("symbol")
        name = det.get("name") or ident.name
        return CardInfoResponse(
            identification=ident,
            card_name=name,
            set_name=set_obj.get("name") or sinfo.get("name"),
            set_code=sid,
            card_number=f"{lid}/{official}" if lid and official else lid,
            rarity=det.get("rarity"),
            supertype=det.get("category"),
            subtypes=[det["stage"]] if det.get("stage") else [],
            hp=str(det["hp"]) if det.get("hp") is not None else None,
            types=det.get("types") or [],
            artist=det.get("illustrator"),
            image_url=f"{img}/high.webp" if img else None,
            cardmarket_url=reverse_raw.get("url")
            or build_cardmarket_search_url(name, lid, set_obj.get("name"), language=ident.language),
            prices=self._merge_prices(cm, listings),
            listings=listings[:25],
            data_source="Cardmarket (reverse-api-engineer)" if listings else "Cardmarket (via TCGdex)",
            alternatives=alternatives,
            tcgdex_id=det.get("id"),
            set_symbol_url=f"{symbol}.png" if symbol else None,
            match_info=match_info,
        )

    # ------------------------------------------------------------------ public API
    async def lookup_card(self, ident: CardIdentification, user_card=None) -> CardInfoResponse:
        listings, reverse_raw = self._reverse_listings(ident)
        client = self._get_http()
        if True:
            await self._ensure_sets(client)

            # Percorso ULTRA-VELOCE: se abbiamo numero + totale set (o codice set), risolviamo subito!
            fast_dets = await self._fast_lookup_by_number_and_total(client, ident)
            if fast_dets:
                chosen_det = fast_dets[0]
                why = []
                if ident.set_name:
                    why.append(f"codice {ident.set_name}")
                if ident.card_number:
                    why.append(f"numero {ident.card_number}")
                if ident.total_in_set:
                    why.append(f"totale /{ident.total_in_set}")

                if user_card is not None and len(fast_dets) > 1:
                    sims = await asyncio.gather(
                        *[self._visual_score(client, {"image": d.get("image")}, user_card) for d in fast_dets]
                    )
                    ranked = sorted(zip(sims, fast_dets), key=lambda x: -x[0])
                    chosen_det = ranked[0][1]
                    fast_dets = [d for _, d in ranked]
                    why.append("confronto visivo")

                alts = [
                    {
                        "tcgdex_id": d["id"],
                        "name": d.get("name"),
                        "set_name": (d.get("set") or {}).get("name"),
                        "card_number": d.get("localId"),
                        "image_url": f"{d['image']}/low.webp" if d.get("image") else None,
                    }
                    for d in fast_dets[1:10]
                ]
                return self._build_response(
                    ident, chosen_det, alts, "Abbinata per: " + ", ".join(why), listings, reverse_raw
                )

            briefs = await self._search_briefs(client, ident.name)
            if not briefs:
                return CardInfoResponse(
                    identification=ident, card_name=ident.name, card_number=ident.card_number,
                    cardmarket_url=build_cardmarket_search_url(ident.name),
                    prices=compute_price_summary_from_listings(listings), listings=listings,
                    data_source="Nessuna carta trovata nel catalogo",
                    match_info="Nome non trovato: prova la ricerca manuale",
                )

            variants_norm = {_norm_name(v) for v in self._build_name_variants(ident.name)}
            scored = [(self._score(b, ident, variants_norm), b) for b in briefs]
            scored.sort(key=lambda x: -x[0][0])
            best = scored[0][0][0]
            limit = 8 if ident.card_number else 16
            top = [x for x in scored if x[0][0] >= best - 25][:limit]
            rest = [x for x in scored if x not in top]
            why = list(scored[0][0][1])

            if user_card is not None and len(top) > 1:
                sims = await asyncio.gather(*[self._visual_score(client, b, user_card) for _, b in top])
                top = [((s[0] + sim * 120, s[1]), b) for (s, b), sim in zip(top, sims)]
                top.sort(key=lambda x: -x[0][0])
                why = list(top[0][0][1]) + ["confronto visivo"]

            ordered = [b for _, b in top] + [b for _, b in rest]
            chosen = ordered[0]
            det = await self._fetch_detail(client, chosen["id"]) or {
                "id": chosen["id"], "name": chosen.get("name"), "localId": chosen.get("localId"),
                "image": chosen.get("image"),
            }
            alts = [self._alt_entry(b) for b in ordered[1:13]]
            match_info = "Abbinata per: " + ", ".join(why) if why else "Abbinata solo per nome"
            return self._build_response(ident, det, alts, match_info, listings, reverse_raw)

    async def lookup_by_id(self, tcgdex_id: str) -> Optional[CardInfoResponse]:
        client = self._get_http()
        await self._ensure_sets(client)
        det = await self._fetch_detail(client, tcgdex_id)
        if not det:
            return None
        ident = CardIdentification(name=det.get("name") or tcgdex_id, confidence=1.0, raw_notes="Scelta manuale")
        return self._build_response(ident, det, [], "Scelta manuale", [], {})
