FROM python:3.12-slim

WORKDIR /app

ENV OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    PYTHONUNBUFFERED=1 \
    OCR_BACKEND=tesseract

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-ita \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    httpx \
    python-multipart \
    python-dotenv \
    pydantic \
    pillow \
    numpy \
    opencv-python-headless \
    pytesseract

COPY backend ./backend
COPY static ./static
COPY generated_client ./generated_client

RUN mkdir -p /app/data/saved/photos

EXPOSE 8765

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8765} --workers 1"]
