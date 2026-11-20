FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PORT=8765

RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    httpx \
    python-multipart \
    python-dotenv \
    pydantic \
    pillow \
    numpy \
    opencv-python-headless

COPY backend ./backend
COPY static ./static
COPY generated_client ./generated_client

RUN mkdir -p /app/data/saved/photos && chmod -R 777 /app/data

EXPOSE 8765

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8765} --workers 1"]
