# The code-execution sandbox image (P1-10): the stock python:3.11-slim plus the
# office/data libraries the agent most often needs to CREATE files — spreadsheets,
# documents, slide decks, PDFs, charts. The sandbox runs with --network none, so
# anything not baked in here is simply unavailable at run time.
#
# Build once:              docker build -t ocd-sandbox backend/sandbox
# The backend auto-uses `ocd-sandbox:latest` when it exists locally; override with
# the CODE_EXEC_IMAGE environment variable to use any other image.
FROM python:3.11-slim

RUN pip install --no-cache-dir \
    pandas \
    numpy \
    matplotlib \
    openpyxl \
    python-docx \
    python-pptx \
    reportlab \
    Pillow

# Match the backend's invocation: code arrives on stdin, workdir is mounted at /w.
WORKDIR /w
