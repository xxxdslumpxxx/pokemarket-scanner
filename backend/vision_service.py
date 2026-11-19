"""
Riconoscimento carta Pokémon con modello ONNX locale (RapidOCR), stile add-on Home Assistant:
  1. Trova e raddrizza la carta nella foto (OpenCV)
  2. OCR SOLO sulle due fasce utili (nome in alto, codici in basso) -> molto più veloce
  3. Fallback OCR sulla carta intera solo se serve
"""
import asyncio
import re
import threading
import time
from typing import Any, NamedTuple, Optional

import cv2
import numpy as np

from .image_match import CARD_H, CARD_W, prepare_card
from .models import CardIdentification

LANG_CODES = {
    "EN": "English", "IT": "Italiano", "FR": "Français", "DE": "Deutsch",
    "ES": "Español", "PT": "Português", "NL": "Nederlands", "JP": "Japanese",
}
IGNORED_CODES = {
    "HP", "PS", "PV", "KP", "TM", "EX", "GX", "NO", "LV", "GAME", "FREAK", "ILLUS",
    "BASIC", "BASE", "V", "VMAX", "VSTAR",
} | set(LANG_CODES)
STAGE_WORDS = re.compile(
    r"^\s*(?:BASIC|BASE|STAGE\s*\d|FASE\s*\d|LIVELLO\s*\d|TRAINER|ALLENATORE|STRUMENTO|ITEM|"
    r"SUPPORTER|AIUTO|STADIUM|STADIO|ENERGY|ENERGIA)\b[\s:]*",
    re.IGNORECASE,
)
NUM_RE = re.compile(
    r"(?<![0-9])((?:TG|GG|SV|RC|H)?[0-9OoIl]{1,3})\s*/\s*((?:TG|GG|SV)?[0-9OoIl]{2,3})(?![0-9])",
    re.IGNORECASE,
)
PROMO_RE = re.compile(r"\b(SWSH|SM|XY|BW)\s*0*(\d{1,3})\b", re.IGNORECASE)


class Block(NamedTuple):
    x: float
    y: float
    h: float
    text: str
    score: float


def _fix_digits(token: str) -> str:
    m = re.match(r"^(TG|GG|SV|RC|H)?(.*)$", token, re.IGNORECASE)
    prefix = (m.group(1) or "").upper()
    rest = m.group(2).replace("O", "0").replace("o", "0").replace("I", "1").replace("l", "1")
    return prefix + rest


class LocalPokemonOCR:
    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()

    def _get_engine(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def warmup(self) -> None:
        img = np.full((96, 320, 3), 255, np.uint8)
        cv2.putText(img, "Pikachu 25/198", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
        self._run(img)

    def _run(self, img: np.ndarray) -> list[Block]:
        h, w = img.shape[:2]
        with self._lock:
            engine = self._get_engine()
            try:
                result, _ = engine(img, use_cls=False)
            except TypeError:
                result, _ = engine(img)
        blocks: list[Block] = []
        for item in result or []:
            box, text, score = item[0], str(item[1]).strip(), float(item[2])
            if not text:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            blocks.append(
                Block(sum(xs) / len(xs) / w, sum(ys) / len(ys) / h, (max(ys) - min(ys)) / h, text, score)
            )
        return blocks

    @staticmethod
    def _pick_name(blocks: list[Block]) -> tuple[Optional[str], float]:
        cands: list[tuple[float, str, float]] = []
        for b in blocks:
            t = b.text
            if re.match(r"^\s*(?:evolves|si evolve|evolve da|entwickelt|évolue)", t, re.IGNORECASE):
                continue
            t = re.sub(r"\b(?:HP|PS|PV|KP)\s*\d{2,3}\b", " ", t, flags=re.IGNORECASE)
            t = re.sub(r"\b\d{2,3}\s*(?:HP|PS|PV|KP)\b", " ", t, flags=re.IGNORECASE)
            t = re.sub(r"\b(?:HP|PS|PV|KP)\b", " ", t, flags=re.IGNORECASE)
            t = STAGE_WORDS.sub("", t)
            t = re.sub(r"[^A-Za-zÀ-ÿ0-9'\-&\.\s]", " ", t)
            t = re.sub(r"\s+", " ", t).strip(" .-")
            letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", t)
            if len(letters) < 3 or letters.upper() in IGNORED_CODES:
                continue
            # Il nome è il testo PIÙ GRANDE della fascia alta, tendenzialmente a sinistra
            prio = b.h * (0.5 + b.score) - (0.4 * b.h if b.x > 0.75 else 0.0)
            cands.append((prio, t, b.score))
        if not cands:
            return None, 0.0
        cands.sort(key=lambda c: -c[0])
        return cands[0][1], cands[0][2]

    @staticmethod
    def _parse_bottom(blocks: list[Block]) -> dict[str, Optional[str]]:
        out: dict[str, Optional[str]] = {"number": None, "total": None, "set_code": None, "lang": None}
        if not blocks:
            return out
        by_x = sorted(blocks, key=lambda b: b.x)
        left = [b for b in by_x if b.x < 0.55]

        # Codice set + lingua (in basso a sinistra, es. "LOR IT 075/196")
        for b in left:
            for tok in re.findall(r"\b[A-Z]{2,4}\b", b.text):
                if tok in LANG_CODES and not out["lang"]:
                    out["lang"] = LANG_CODES[tok]
                elif tok not in IGNORED_CODES and not out["set_code"]:
                    out["set_code"] = tok

        # Numero / totale: prima a sinistra, poi ovunque (i set vecchi con SIMBOLO lo hanno a destra)
        zones = [b.text for b in left] + [b.text for b in by_x] + [" ".join(b.text for b in by_x)]
        for z in zones:
            m = NUM_RE.search(z)
            if m:
                out["number"] = _fix_digits(m.group(1))
                out["total"] = _fix_digits(m.group(2))
                return out
        for z in zones:
            m = PROMO_RE.search(z)
            if m:
                out["set_code"] = m.group(1).upper()
                out["number"] = f"{m.group(1).upper()}{int(m.group(2)):03d}"
                return out
        # Promo SV: "SVP EN 001" (senza slash)
        if out["set_code"] == "SVP":
            m = re.search(r"\b(\d{3})\b", " ".join(b.text for b in left))
            if m:
                out["number"] = m.group(1)
        return out

    @staticmethod
    def _guess_lang(texts: str) -> Optional[str]:
        low = texts.lower()
        if any(w in low for w in ("debolezza", "resistenza", "ritirata", "si evolve")):
            return "Italiano"
        if any(w in low for w in ("weakness", "resistance", "retreat", "evolves from")):
            return "English"
        return None

    def identify(self, image_bytes: bytes) -> tuple[CardIdentification, np.ndarray]:
        t0 = time.perf_counter()
        card, found, _orig = prepare_card(image_bytes)

        top = card[int(CARD_H * 0.015): int(CARD_H * 0.14), :]
        bottom = card[int(CARD_H * 0.865): CARD_H, :]
        bottom = cv2.resize(bottom, None, fx=1.45, fy=1.45, interpolation=cv2.INTER_CUBIC)

        top_blocks = self._run(top)
        bottom_blocks = self._run(bottom)
        name, conf = self._pick_name(top_blocks)
        info = self._parse_bottom(bottom_blocks)
        used_full = False

        if not name or not info["number"]:
            used_full = True
            full = self._run(card)
            if not name:
                name, conf = self._pick_name([b for b in full if b.y < 0.2])
            if not info["number"]:
                info2 = self._parse_bottom([b for b in full if b.y > 0.78])
                info = {k: info.get(k) or info2.get(k) for k in info}
            lang_hint = self._guess_lang(" ".join(b.text for b in full))
        else:
            lang_hint = None

        if not name:
            raise RuntimeError(
                "Non riesco a leggere il nome della carta. Rifai la foto con la carta intera, dritta e senza riflessi."
            )

        ms = int((time.perf_counter() - t0) * 1000)
        ident = CardIdentification(
            name=name,
            set_name=info["set_code"],
            card_number=info["number"],
            total_in_set=info["total"],
            language=info["lang"] or lang_hint or "N/D",
            condition_estimate=None,
            is_holo=False,
            confidence=round(min(max(conf, 0.3), 0.99), 2),
            raw_notes=f"ONNX locale in {ms} ms | carta {'ritagliata' if found else 'non ritagliata'}"
            + (" | OCR completo" if used_full else ""),
        )
        return ident, card


class VisionCardRecognizer:
    """Riconoscimento 100% locale con ONNX (nessuna API key)."""

    def __init__(self) -> None:
        self._local_ocr = LocalPokemonOCR()

    @property
    def configured_provider(self) -> str:
        return "ONNX Locale (Zero API Key)"

    def warmup(self) -> None:
        self._local_ocr.warmup()

    async def identify(self, image_bytes: bytes) -> tuple[CardIdentification, Any]:
        return await asyncio.to_thread(self._local_ocr.identify, image_bytes)
