# syntax=docker/dockerfile:1

# Python 3.10, not something newer: the requirements are pinned to the 2023
# stack (langchain 0.0.300, openai 0.27.8, chromadb 0.4.3) and chroma-hnswlib
# 0.7.1 has no wheels for 3.12.
FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# chroma-hnswlib is a C++ extension with no wheel for this image, so pip
# compiles it and needs a toolchain. The apt lists go in the same RUN because
# a later layer cannot shrink an earlier one. Note that build-essential itself
# stays in the image; purging it here, or splitting this into a multi-stage
# build, is the trade to make if image size ever becomes the problem.
RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements first, so a source-only change does not reinstall 130 packages.
COPY src/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Build the corpus into the image: download the 39 source PDFs, embed them,
# and persist Chroma under app/documents/vector_store. Only the ingestion
# package is copied at this point, so this layer (and the embedding spend) is
# rebuilt when the pipeline or the sources CSV changes, not on every edit to a
# view or template.
#
# The key arrives as a BuildKit secret: mounted for this one RUN, never
# written to a layer or the image history. Pass it with
#   fly deploy --build-secret OPENAI_API_KEY=...
# required=true turns a forgotten flag into a clear "secret not found" error
# instead of an embedding failure halfway through.
#
# The ingestion gate still applies: if any document fails to download, the
# build fails rather than shipping a short index. ALLOW_PARTIAL_CORPUS=1, as
# a --build-arg, is the deliberate override.
#
# The PDFs are deleted in the same RUN. Answers link to the publishers' own
# URLs, so nothing at runtime reads them, and removing them in a later layer
# would not shrink the image.
COPY src/app/__init__.py ./app/__init__.py
COPY src/app/documents/ ./app/documents/
ARG ALLOW_PARTIAL_CORPUS=
RUN --mount=type=secret,id=OPENAI_API_KEY,required=true \
    OPENAI_API_KEY="$(cat /run/secrets/OPENAI_API_KEY)" \
    python -m app.documents.data_utils process_source_documents \
    && rm -rf app/documents/files/comply_sources

# .dockerignore keeps any local vector_store out of the context, so this
# cannot overwrite the index built above.
COPY src/ ./

# Whitenoise serves from STATIC_ROOT, which only exists once collectstatic has
# run. The placeholder values are build-time only and never reach the image's
# runtime environment — collectstatic needs the settings module to import, not
# a working key.
#
# OPENAI_API_KEY is here because app.apps.AppConfig.ready() builds the chain at
# startup, which imports vector_store, which constructs OpenAIEmbeddings at
# import time and refuses to load without a key. Making that lazy is the next
# piece of work; once it lands, this line loses the key and the build stops
# depending on a credential it never uses.
RUN SECRET_KEY=build-only-not-a-secret \
    DJANGO_ALLOWED_HOSTS=localhost \
    OPENAI_API_KEY=sk-build-placeholder \
    python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "-c", "gunicorn_config.py"]
