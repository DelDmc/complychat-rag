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
