import io
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageOps

ROOT_DIR = Path(__file__).resolve().parent.parent
SAVED_DIR = ROOT_DIR / "data" / "saved"
PHOTOS_DIR = SAVED_DIR / "photos"
INDEX_FILE = SAVED_DIR / "index.json"

_lock = threading.Lock()


def _load() -> list[dict[str, Any]]:
    if not INDEX_FILE.exists():
        return []
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write(items: list[dict[str, Any]]) -> None:
    SAVED_DIR.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    tmp.replace(INDEX_FILE)


def list_saved() -> list[dict[str, Any]]:
    with _lock:
        return sorted(_load(), key=lambda x: x.get("saved_at", 0), reverse=True)


def add_saved(card: dict[str, Any], photo_bytes: Optional[bytes]) -> dict[str, Any]:
    item_id = uuid.uuid4().hex[:12]
    photo_url = None
    if photo_bytes:
        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        with Image.open(io.BytesIO(photo_bytes)) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((900, 900))
            img.save(PHOTOS_DIR / f"{item_id}.jpg", format="JPEG", quality=82)
        photo_url = f"/saved_photos/{item_id}.jpg"
    entry = {"id": item_id, "saved_at": time.time(), "photo_url": photo_url, "card": card}
    with _lock:
        items = _load()
        items.append(entry)
        _write(items)
    return entry


def delete_saved(item_id: str) -> bool:
    with _lock:
        items = _load()
        new_items = [i for i in items if i.get("id") != item_id]
        if len(new_items) == len(items):
            return False
        _write(new_items)
    photo = PHOTOS_DIR / f"{item_id}.jpg"
    if photo.exists():
        photo.unlink()
    return True
