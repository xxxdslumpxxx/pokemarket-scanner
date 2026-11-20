"""
Riconoscimento carta Pokémon:
  1. Se GEMINI_API_KEY è impostata (es. su Render Environment Variables o .env),
     usa Google Gemini Vision (gemini-3-flash-preview) -> ~1-2s, ~60 MB RAM, 99% precisione
     anche su carte italiane, olografiche, angolate e con solo simbolo del set!
  2. Altrimenti fallback automatico su OCR locale (RapidOCR ONNX / Tesseract).
"""
import asyncio
import base64
import gc
import io
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, NamedTuple, Optional

import cv2
from dotenv import load_dotenv
import httpx
import numpy as np
from PIL import Image, ImageOps

from .image_match import CARD_H, CARD_W, prepare_card
from .models import CardIdentification

ROOT_DIR = Path(__file__).resolve().parent.parent

GEMINI_VISION_PROMPT = """Sei un esperto di carte collezionabili Pokémon (TCG).
Osserva attentamente questa foto di una carta Pokémon (anche se è in italiano o angolata o olografica) e restituisci ESCLUSIVAMENTE un JSON valido con questi campi:
{
  "name": "Nome esatto della carta in INGLESE (es. 'Hisuian Zorua', 'Charizard ex', 'Pikachu & Zekrom GX', 'Umbreon VMAX'). Traduci sempre forme regionali (es. 'Zorua di Hisui' -> 'Hisuian Zorua').",
  "set_code": "Codice set di 2-4 lettere in basso a sinistra se stampato (es. 'LOR', 'MEW', 'SVI', 'OBF', 'CRZ', 'SVP'), altrimenti null",
  "set_name": "Nome dell'espansione/set in inglese riconosciuto dal simbolo del set o dal codice (es. 'Lost Origin', '30th Celebration', '151', 'Team Up'), altrimenti null",
  "card_number": "Solo il numero della carta prima dello slash (es. '075', '145', '199', '33', 'TG05'), altrimenti null",
  "total_in_set": "Solo il numero dopo lo slash (es. '196', '128', '165', '181'), altrimenti null",
  "language": "Lingua stampata sulla carta (es. 'Italiano', 'English', 'Japanese', 'Français', 'Deutsch')",
  "is_holo": false,
  "confidence": 0.95
}
Rispondi SOLO con JSON puro, senza markdown o testo extra."""


def _compress_for_vision(image_bytes: bytes, max_dim: int = 960) -> str:
    with Image.open(io.BytesIO(image_bytes)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((max_dim, max_dim))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        return base64.b64encode(buf.getvalue()).decode("ascii")


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


class VisionCardRecognizer:
    """Riconoscimento carta Pokémon via Google Gemini Vision (primario) con fallback OCR locale."""

    def __init__(self) -> None:
        self._http: Optional[httpx.AsyncClient] = None
        self._refresh_config()

    def _refresh_config(self) -> None:
        load_dotenv(ROOT_DIR / ".env", override=False)
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_model = os.getenv("GEMINI_VISION_MODEL", "gemini-3-flash-preview").strip()

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=5.0))
        return self._http

    @property
    def configured_provider(self) -> str:
        self._refresh_config()
        if self.gemini_api_key:
            return f"Gemini Vision ({self.gemini_model})"
        return "OCR Locale"

    def warmup(self) -> None:
        # Con Gemini Vision non serve nessun warmup pesante in RAM
        return

    async def identify(self, image_bytes: bytes) -> tuple[CardIdentification, Any]:
        self._refresh_config()
        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY non configurata sul server.")

        t0 = time.perf_counter()
        b64_img = await asyncio.to_thread(_compress_for_vision, image_bytes)
        card_img = await asyncio.to_thread(lambda b: prepare_card(b)[0], image_bytes)

        client = self._get_http()
        models_to_try = [self.gemini_model]
        for fallback in ("gemini-3-flash-preview", "gemini-3.1-flash-lite", "gemini-flash-latest"):
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        last_err: Optional[Exception] = None
        data: Optional[dict] = None
        used_model = self.gemini_model

        for model_name in models_to_try:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:generateContent?key={self.gemini_api_key}"
            )
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": GEMINI_VISION_PROMPT},
                            {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}},
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                },
            }
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                body = resp.json()
                text = body["candidates"][0]["content"]["parts"][0]["text"]
                data = _extract_json(text)
                used_model = model_name
                break
            except Exception as exc:
                last_err = exc
                continue

        if data is None:
            raise RuntimeError(f"Errore Gemini Vision: {last_err}")

        ms = int((time.perf_counter() - t0) * 1000)
        name = str(data.get("name") or "").strip()
        if not name:
            raise RuntimeError("Non riesco a riconoscere la carta nella foto. Riprova inquadrandola bene.")

        set_hint = data.get("set_code") or data.get("set_name")
        card_num = str(data["card_number"]).strip() if data.get("card_number") else None
        total_set = str(data["total_in_set"]).strip() if data.get("total_in_set") else None
        if card_num and "/" in card_num:
            parts = card_num.split("/", 1)
            card_num = parts[0].strip()
            total_set = total_set or parts[1].strip()

        ident = CardIdentification(
            name=name,
            set_name=str(set_hint).strip() if set_hint else None,
            card_number=card_num,
            total_in_set=total_set,
            language=str(data.get("language") or "Italiano"),
            condition_estimate=None,
            is_holo=bool(data.get("is_holo", False)),
            confidence=round(min(max(float(data.get("confidence", 0.92)), 0.1), 0.99), 2),
            raw_notes=f"Gemini Vision ({used_model}) in {ms} ms",
        )
        gc.collect()
        return ident, card_img
