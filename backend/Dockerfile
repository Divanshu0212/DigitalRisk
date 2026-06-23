# Backend image: FastAPI + asyncpg served by uvicorn.
# Multi-stage not used — image is small enough with slim base.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose the API port; uvicorn binds via compose / run command.
EXPOSE 8000

# Single worker for local dev. In prod, run behind gunicorn -k uvicorn.workers.UvicornWorker -w <N>.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
