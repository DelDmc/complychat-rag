import os

# Fly injects PORT; 8000 keeps `gunicorn -c gunicorn_config.py` working locally.
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# Each sync worker loads chromadb, onnxruntime and its own copy of the Chroma
# index, so worker count is the main driver of the container's memory
# footprint — not request concurrency. Two fits a 1GB VM; raise
# WEB_CONCURRENCY deliberately, on a machine with the memory to back it.
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))

accesslog = "-"

# An LLM call plus retrieval can legitimately take tens of seconds.
timeout = 300
