FROM python:3.12-slim
# Eski Office formatlarını (.doc .ppt .xls) okumak için LibreOffice (≈400 MB). İstemiyorsanız:
#   docker compose build --build-arg WITH_LIBREOFFICE=0
ARG WITH_LIBREOFFICE=1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data STORAGE_DIR=/files HOME=/tmp
RUN if [ "$WITH_LIBREOFFICE" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends libreoffice-writer libreoffice-calc libreoffice-impress \
      && rm -rf /var/lib/apt/lists/*; fi
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd -r -u 10001 appuser && mkdir -p /data /files && chown appuser /data /files
USER appuser
VOLUME ["/data", "/files"]
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/saglik')" || exit 1
# Tek işçi (worker): arka plan doküman kuyruğu uygulama süreci içinde çalışır.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
