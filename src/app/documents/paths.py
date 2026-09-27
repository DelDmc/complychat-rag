'''Shared filesystem locations for the document pipeline.

These paths are anchored to this module's own directory rather than the
current working directory, so the pipeline behaves identically no matter
where Python is invoked from (``src/``, the repository root, or elsewhere).
'''

import os
from pathlib import Path

# .../src/app/documents — every corpus path hangs off this.
DOCUMENTS_DIR: Path = Path(__file__).resolve().parent

# Directory the 39 public source PDFs are downloaded into, using the exact
# ``filename`` recorded in the sources CSV. Read by PDFLoader and PDFDownloader.
APP_DOCS_DIR: Path = DOCUMENTS_DIR / 'files' / 'comply_sources'

# Persistent Chroma storage written by the ingestion step. On Fly it lives on
# the machine's volume, and fly.toml points VECTOR_STORE_DIR there; it must be
# an absolute path. Everywhere else it defaults to a directory beside this one.
VECTOR_STORE_DIR: Path = (Path(os.environ['VECTOR_STORE_DIR'])
                          if os.environ.get('VECTOR_STORE_DIR')
                          else DOCUMENTS_DIR / 'vector_store')

# The Chroma subdirectory passed to chromadb.PersistentClient.
CHROMA_DIR: Path = VECTOR_STORE_DIR / 'chroma'
