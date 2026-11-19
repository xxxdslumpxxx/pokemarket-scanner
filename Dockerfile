FROM python:3.12-slim

WORKDIR /app

ENV OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    ORT_LOGGING_LEVEL=3 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    httpx \
    python-multipart \
    python-dotenv \
    pydantic \
    pillow \
    opencv-python-headless \
    rapidocr-onnxruntime

COPY backend ./backend
COPY static ./static
COPY generated_client ./generated_client

RUN mkdir -p /app/data/saved/photos

EXPOSE 8765

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8765} --workers 1"]
