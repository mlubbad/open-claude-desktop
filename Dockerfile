# Chainlit chat app (app.py).
# The Reflex projects UI (aj360_app/) needs a separate node+python image and is
# not built here.
FROM python:3.12-slim

# PYTHONPATH: app.py imports the ocd_core package, which lives under backend/ and
# is not pip-installed, so backend/ must be importable at runtime.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/appuser \
    PYTHONPATH=/app/backend

# Unprivileged runtime user, created up front so it can own /app and write the
# runtime data dirs (chroma_db/, logs/, projects/, ...) created under WORKDIR.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app
RUN chown appuser:appuser /app

COPY requirements.txt ./
# requirements.txt is a complete pinned freeze, so install with --no-deps and let
# pip skip re-resolution. A fresh resolve fails: zhipuai pins PyJWT<2.9 while
# chainlit/mcp declare a newer PyJWT -- the pinned set installs fine together.
RUN pip install --no-deps -r requirements.txt

COPY --chown=appuser:appuser . .

# Drop root before running the server.
USER appuser

EXPOSE 8000

# BigQuery uses Application Default Credentials — provide them at runtime via
# Workload Identity or by mounting a key and setting GOOGLE_APPLICATION_CREDENTIALS
# (see the commented block in docker-compose.yml).
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
