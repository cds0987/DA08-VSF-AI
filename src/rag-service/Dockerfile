# Pin by immutable digest (not a mutable tag) — tag kept for readability only.
# Digest = index của python:3.13.4-slim-bookworm (resolve lại khi bump version).
FROM python:3.13.4-slim-bookworm@sha256:9ed09f78253eb4f029f3d99e07c064f138a6f1394932c3807b3d0738a674d33b

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_ENV=production

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/* \
    && adduser --disabled-password --gecos "" appuser

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3).status==200 else 1)"

CMD ["uvicorn", "app.interfaces.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
