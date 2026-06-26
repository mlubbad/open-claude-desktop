# Chainlit chat app (app.py).
# The Reflex projects UI (aj360_app/) needs a separate node+python image and is
# not built here.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

# BigQuery uses Application Default Credentials — provide them at runtime via
# Workload Identity or by mounting a key and setting GOOGLE_APPLICATION_CREDENTIALS
# (see the commented block in docker-compose.yml).
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
