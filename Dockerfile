# syntax=docker/dockerfile:1.7
#
# Production image for the songs.ai bot.
#
# Lavalink runs in a separate container (see docker-compose.yml); this
# image only contains the Python bot itself.

FROM python:3.12-slim AS base

# - PYTHONDONTWRITEBYTECODE: don't litter the image with .pyc files
# - PYTHONUNBUFFERED: make stdout/stderr appear in `docker logs` immediately
# - PIP_NO_CACHE_DIR: smaller image, no wheel cache left behind
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Create a non-root user up front so we can chown things to it later.
RUN groupadd --system app && useradd --system --gid app --create-home app

# ---- dependency layer ----
# Copy requirements first so pip install is cached unless requirements.txt
# actually changes - much faster iterative builds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- app layer ----
COPY . .

# Make sure the app user can read everything and write to /app/data.
RUN mkdir -p /app/data && chown -R app:app /app

USER app

# /app/data is mounted as a Docker volume in docker-compose.yml so the
# SQLite file survives `docker compose up -d --build` cycles.
ENV SONGS_DB_PATH=/app/data/songs.sqlite

# No EXPOSE - the bot only makes outbound connections (to Discord, Lavalink,
# Jamendo, etc.). There is no inbound HTTP surface to publish.

CMD ["python", "main.py"]
