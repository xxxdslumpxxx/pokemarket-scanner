"""
Utility immagine (OpenCV):
  - prepare_card: trova la carta nella foto e la raddrizza (prospettiva) -> immagine carta pulita
  - similarity: confronto visivo artwork tra la foto dell'utente e l'immagine ufficiale di una carta
    (usato per distinguere i set che hanno solo il SIMBOLO e non il codice testuale).
"""
import io
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageOps

CARD_W, CARD_H = 560, 782  # proporzione 63:88 (ottimizzata per OCR rapido)


def decode_to_bgr(image_bytes: bytes, max_side: int = 1600) -> np.ndarray:
    with Image.open(io.BytesIO(image_bytes)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((max_side, max_side))
        arr = np.array(img)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    d = np.diff(pts, axis=1).ravel()
    rect[1] = pts[np.argmin(d)]
    rect[3] = pts[np.argmax(d)]
    return rect


def find_card(img_bgr: np.ndarray) -> Optional[np.ndarray]:
    """Cerca il contorno a 4 lati della carta e restituisce la carta raddrizzata, oppure None."""
    h, w = img_bgr.shape[:2]
    scale = 800.0 / max(h, w) if max(h, w) > 800 else 1.0
    small = cv2.resize(img_bgr, (int(w * scale), int(h * scale))) if scale != 1.0 else img_bgr
    area_img = small.shape[0] * small.shape[1]

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    for lo, hi in ((40, 130), (20, 80), (60, 180)):
        edges = cv2.Canny(gray, lo, hi)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:6]:
            area = cv2.contourArea(c)
            if area < 0.12 * area_img:
                break
            if area > 0.985 * area_img:
                continue  # è il bordo della foto, non la carta
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) != 4:
                continue
            pts = approx.reshape(4, 2).astype("float32") / scale
            rect = _order_points(pts)
            tl, tr, br, bl = rect
            cw = max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))
            ch = max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))
            if cw <= 0 or ch <= 0:
                continue
            ratio = min(cw, ch) / max(cw, ch)
            if not 0.62 < ratio < 0.82:
                continue
            if cw > ch:  # carta in orizzontale -> ruota
                rect = np.array([bl, tl, tr, br], dtype="float32")
            dst = np.array(
                [[0, 0], [CARD_W - 1, 0], [CARD_W - 1, CARD_H - 1], [0, CARD_H - 1]], dtype="float32"
            )
            m = cv2.getPerspectiveTransform(rect, dst)
            return cv2.warpPerspective(img_bgr, m, (CARD_W, CARD_H))
    return None


def prepare_card(image_bytes: bytes) -> tuple[np.ndarray, bool, np.ndarray]:
    """Restituisce (carta_raddrizzata, trovata_contorno, immagine_originale)."""
    orig = decode_to_bgr(image_bytes)
    card = find_card(orig)
    if card is not None:
        return card, True, orig
    # Fallback: l'utente ha inquadrato la carta a tutto schermo
    return cv2.resize(orig, (CARD_W, CARD_H), interpolation=cv2.INTER_AREA), False, orig


def _signature(card_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c = cv2.resize(card_bgr, (126, 176), interpolation=cv2.INTER_AREA)
    art = c[int(176 * 0.10): int(176 * 0.52), int(126 * 0.07): int(126 * 0.93)]
    gray = cv2.cvtColor(art, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(cv2.resize(gray, (48, 36), interpolation=cv2.INTER_AREA))
    hsv = cv2.cvtColor(art, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [18, 8], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return gray.astype(np.float32), hist


def similarity(user_card_bgr: np.ndarray, ref_bytes: bytes) -> float:
    """Punteggio 0..1 circa: quanto l'artwork della foto somiglia all'immagine ufficiale."""
    try:
        ref = decode_to_bgr(ref_bytes, max_side=600)
        ga, ha = _signature(user_card_bgr)
        gb, hb = _signature(ref)
        ncc = float(cv2.matchTemplate(ga, gb, cv2.TM_CCOEFF_NORMED)[0][0])
        hc = float(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL))
        return max(0.0, 0.6 * ncc + 0.4 * hc)
    except Exception:
        return 0.0
