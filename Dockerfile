FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/app \
    HF_HOME=/home/app/.cache/huggingface \
    XDG_CACHE_HOME=/home/app/.cache

WORKDIR /app

RUN addgroup --system app \
    && adduser --system --ingroup app --home /home/app app \
    && mkdir -p /home/app/.cache/huggingface \
    && chown -R app:app /home/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

USER app
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
