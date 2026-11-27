FROM python:3.12-slim

# requirements.txt       -> slim cloud image (Gemini Live), fits free hosting tiers
# requirements-local.txt -> adds the self-hosted faster-whisper and Piper models
ARG REQUIREMENTS=requirements.txt

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

COPY requirements*.txt ./
RUN pip install -r ${REQUIREMENTS}

COPY app ./app
COPY static ./static
COPY scripts ./scripts

RUN useradd --create-home --uid 10001 vaani && mkdir -p /app/models && chown -R vaani /app/models
USER vaani

EXPOSE 8000
# Hosting platforms (Render, Railway, Cloud Run, ...) tell the app which port to use via $PORT.
# --proxy-headers: trust X-Forwarded-* from the platform's HTTPS proxy.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
