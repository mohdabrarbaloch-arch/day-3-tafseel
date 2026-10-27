FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# Dependencies first so the layer caches between code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY api ./api

# Run as a non-root user -- a container that can write to /srv is a container that
# can rewrite its own code.
RUN groupadd -r tafseel && useradd -r -g tafseel tafseel && \
    mkdir -p /data && chown -R tafseel:tafseel /srv /data

USER tafseel

ENV DATABASE_URL=sqlite:////data/tafseel.db \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
