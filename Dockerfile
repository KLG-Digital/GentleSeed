FROM python:3.12-slim

ENV GENTLESEED_CONTAINER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home app
COPY backend ./backend
COPY web ./web
RUN mkdir -p /data && chown app:app /data
USER app
EXPOSE 1853
# Contrôle de santé : la page de connexion (publique) doit répondre
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:1853/login', timeout=3)"
CMD ["uvicorn", "backend.webui:app", "--host", "0.0.0.0", "--port", "1853", "--workers", "1", "--no-access-log"]
