# Runs on a Raspberry Pi 4/5 (arm64) as well as x86 -- every dependency here
# ships prebuilt aarch64 wheels, so there is nothing to compile on the Pi.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer is cached across code changes, which is the
# difference between a 10-second and a 3-minute rebuild on a Pi.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini entrypoint.sh ./
COPY alembic ./alembic
COPY app ./app

# uid 1000 matches the default Raspberry Pi OS user, so the bind-mounted
# ./data directory stays writable without a chown dance.
RUN chmod +x entrypoint.sh \
 && useradd --uid 1000 --create-home appuser \
 && mkdir -p /data \
 && chown -R appuser:appuser /data /app
USER appuser

EXPOSE 3000
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/healthz')"

CMD ["./entrypoint.sh"]
