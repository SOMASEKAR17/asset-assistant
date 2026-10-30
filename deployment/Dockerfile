FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/vendor/engine HF_HOME=/models DEMO_HOME=/data DEMO_LIBRARY=/library DEMO_SEED=/seed
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY vendor/requirements.txt vendor/requirements-ml.txt /tmp/
RUN pip install -r /tmp/requirements.txt -r /tmp/requirements-ml.txt
COPY vendor/engine /app/vendor/engine
COPY vendor/LICENSE /app/vendor/LICENSE
COPY server.py prepare_library.py cloud.py uploads.py private_api.py upload_worker.py /app/
COPY site /app/site
RUN useradd --uid 10001 --create-home demo && mkdir -p /library /seed /models /data /uploads \
    && chown demo:demo /data /models /uploads
USER demo
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-proxy-headers", "--limit-concurrency", "32", "--timeout-keep-alive", "5"]
