FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    OCR_BACKEND=rapidocr \
    PORT=7860

RUN apt-get update && apt-get install -y --no-install-recommends \
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
    rapidocr-onnxruntime

COPY backend ./backend
COPY static ./static
COPY generated_client ./generated_client

RUN mkdir -p /app/data/saved/photos && chmod -R 777 /app/data

EXPOSE 7860

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
