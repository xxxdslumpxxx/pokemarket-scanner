import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import saved_store
from .cardmarket_parser import extract_cardmarket_from_har
from .cardmarket_reverse_client import CAPTURES_DIR, CardmarketService
from .models import CardIdentification, CardInfoResponse
from .vision_service import VisionCardRecognizer

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "static"
saved_store.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="PokéMarket Scanner API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

vision_service = VisionCardRecognizer()
cardmarket_service = CardmarketService()


@app.on_event("startup")
async def _warmup() -> None:
    # Carica subito modello ONNX e cache set TCGdex, così anche la PRIMA scansione è rapidissima
    threading.Thread(target=vision_service.warmup, daemon=True).start()
    asyncio.create_task(cardmarket_service._ensure_sets(cardmarket_service._get_http()))


@app.get("/api/status")
async def get_status():
    return {
        "status": "ok",
        "vision_provider": vision_service.configured_provider,
        "vision_ready": True,
        "reverse_api_client_loaded": cardmarket_service.reverse_api_connected,
        "captured_hars": cardmarket_service.get_imported_har_summary(),
    }


@app.post("/api/scan", response_model=CardInfoResponse)
async def scan_card(file: UploadFile = File(...)):
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Immagine vuota.")
    t0 = time.perf_counter()
    try:
        identification, card_img = await vision_service.identify(image_bytes)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Errore lettura foto: {exc}") from exc
    t1 = time.perf_counter()
    result = await cardmarket_service.lookup_card(identification, user_card=card_img)
    t2 = time.perf_counter()
    result.timings = {"ocr_ms": int((t1 - t0) * 1000), "lookup_ms": int((t2 - t1) * 1000)}
    return result


@app.get("/api/search", response_model=CardInfoResponse)
async def search_card(
    name: str = Query(..., min_length=2),
    number: Optional[str] = Query(default=None),
    set_name: Optional[str] = Query(default=None),
):
    num, total = (number or "").strip() or None, None
    if num and "/" in num:
        num, total = [p.strip() or None for p in num.split("/", 1)]
    ident = CardIdentification(
        name=name.strip(), card_number=num, total_in_set=total,
        set_name=(set_name or "").strip() or None, confidence=1.0, raw_notes="Ricerca manuale",
    )
    t0 = time.perf_counter()
    result = await cardmarket_service.lookup_card(ident)
    result.timings = {"lookup_ms": int((time.perf_counter() - t0) * 1000)}
    return result


@app.get("/api/card/{tcgdex_id}", response_model=CardInfoResponse)
async def get_card(tcgdex_id: str):
    result = await cardmarket_service.lookup_by_id(tcgdex_id)
    if not result:
        raise HTTPException(status_code=404, detail="Carta non trovata.")
    return result


@app.get("/api/saved")
async def get_saved():
    return saved_store.list_saved()


@app.post("/api/saved")
async def save_card(payload: str = Form(...), photo: Optional[UploadFile] = File(default=None)):
    try:
        card = json.loads(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Dati carta non validi.") from exc
    photo_bytes = await photo.read() if photo else None
    return await asyncio.to_thread(saved_store.add_saved, card, photo_bytes or None)


@app.delete("/api/saved/{item_id}")
async def delete_saved(item_id: str):
    if not saved_store.delete_saved(item_id):
        raise HTTPException(status_code=404, detail="Elemento non trovato.")
    return {"deleted": item_id}


@app.post("/api/reverse-api/import-har")
async def import_har(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        har_data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"File HAR non valido: {exc}") from exc
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "cardmarket_capture.har").name
    if not safe_name.endswith(".har"):
        safe_name += ".har"
    (CAPTURES_DIR / safe_name).write_bytes(raw)
    parsed = extract_cardmarket_from_har(har_data)
    return {"saved_as": safe_name, "endpoints_discovered": len(parsed["endpoints"])}


@app.get("/")
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/saved_photos", StaticFiles(directory=saved_store.PHOTOS_DIR), name="saved_photos")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
